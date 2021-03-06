"""
Module for generation of random atomic crystals with symmetry constraints. A
pymatgen- or spglib-type structure object is created, which can be saved to a
.cif file. Options (preceded by two dashes) are provided for command-line usage
of the module:  

    spacegroup (-s): the international spacegroup number (between 1 and 230)
        to be generated. In the case of a 2D crystal (using option '-d 2'),
        this will instead be the layer group number (between 1 and 80).
        Defaults to 36.  

    element (-e): the chemical symbol of the atom(s) to use. For multiple
        molecule types, separate entries with commas. Ex: "C", "H, O, N".
        Defaults to "Li"  

    numIons (-n): the number of atoms in the PRIMITIVE unit cell
        (For P-type spacegroups, this is the same as the number of molecules in
        the conventional unit cell. For A, B, C, and I-centered spacegroups,
        this is half the number of the conventional cell. For F-centered unit
        cells, this is one fourth the number of the conventional cell.).
        For multiple atom types, separate entries with commas.
        Ex: "8", "1, 4, 12". Defaults to 16  

    factor (-f): the relative volume factor used to generate the unit cell.
        Larger values result in larger cells, with atoms spaced further apart.
        If generation fails after max attempts, consider increasing this value.
        Defaults to 1.0  

    verbosity (-v): the amount of information which should be printed for each
        generated structure. For 0, only prints the requested and generated
        spacegroups. For 1, also prints the contents of the generated pymatgen
        structure. Defaults to 0  

    attempts (-a): the number of structures to generate. Note: if any of the
        attempts fail, the number of generated structures will be less than this
        value. Structures will be output to separate cif files. Defaults to 1  

    outdir (-o): the file directory where cif files will be output to.
        Defaults to "out"  

    dimension (-d): 3 for 3D, or 2 for 2D, 1 for 1D. If 2D, generates a 2D
        crystal using a layer group number instead of a space group number. For
        1D, we use a Rod group number. Defaults to 3  

    thickness (-t): The thickness, in Angstroms, to use when generating a
        2D crystal. Note that this will not necessarily be one of the lattice
        vectors, but will represent the perpendicular distance along the non-
        periodic direction. For 1D crystals, we use this value
        as the cross-sectional area of the crystal. Defaults to None  
"""

import sys
from time import time
from os.path import exists

from spglib import get_symmetry_dataset
from pymatgen.core.structure import Structure
from pymatgen.core.structure import Molecule
from pymatgen.io.cif import CifWriter

from optparse import OptionParser
from scipy.spatial.distance import cdist
import numpy as np
from random import uniform as rand_u
from random import choice as choose
from random import randint
from math import sqrt, pi, sin, cos, acos, fabs
from copy import deepcopy

from pyxtal.database.element import Element
import pyxtal.database.hall as hall
from pyxtal.database.layergroup import Layergroup
from pyxtal.operations import OperationAnalyzer
from pyxtal.operations import angle
from pyxtal.operations import random_vector
from pyxtal.operations import are_equal
from pyxtal.operations import random_shear_matrix
from pyxtal.symmetry import *

#some optional libs
#from vasp import read_vasp
#from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
#from os.path import isfile

#Define variables
#------------------------------
tol_m = 1.0 #seperation tolerance in Angstroms
max1 = 30 #Attempts for generating lattices
max2 = 30 #Attempts for a given lattice
max3 = 30 #Attempts for a given Wyckoff position
minvec = 2.0 #minimum vector length
#Matrix for a Euclidean metric
Euclidean_lattice = np.array([[1,0,0],[0,1,0],[0,0,1]])


#Define functions
#------------------------------
class Tol_matrix():
    """
    Class for variable distance tolerance checking. Used within random_crystal and
    molecular_crystal to verify whether atoms are too close. Stores a matrix of atom-
    atom pair tolerances. Note that the matrix's indices correspond to atomic numbers,
    with the 0th entries being 0 (there is no atomic number 0).

    Args:
        prototype: a string representing the type of radii to use
            ("atomic", "molecular", or "metallic")
        factor: a float to scale the distances by. A smaller value means a smaller
            tolerance for distance checking
        tuples: a list or tuple of tuples, which define custom tolerance values. Each tuple
            should be of the form (specie1, specie2, value), where value is the tolerance
            in Angstroms, and specie1 and specie2 can be strings, integers, Element objects,
            or pymatgen Specie objects. Custom values may also be set using set_tol
    """
    def __init__(self, *tuples, prototype="atomic", factor=1.0):
        f = factor
        self.prototype = prototype
        if prototype == "atomic":
            f *= 0.5
            attrindex = 5
            self.radius_type = "covalent"
        elif prototype == "molecular":
            attrindex = 5
            self.radius_type = "covalent"
            f *= 1.2
        elif prototype == "metallic":
            attrindex = 7
            self.radius_type = "metallic"
            f *= 0.5
        else:
            self.radius_type = "N/A"
        self.f = f
        H = Element('H')
        m = [[0.]*(len(H.elements_list)+1)]
        for i, tup1 in enumerate(H.elements_list):
            m.append([0.])
            for j, tup2 in enumerate(H.elements_list):
                #Get the appropriate atomic radii
                if tup1[attrindex] is None:
                    if tup1[5] is None:
                        val1 = None
                    else:
                        #Use the covalent radius
                        val1 = tup1[5]
                else:
                    val1 = tup1[attrindex]
                if tup2[attrindex] is None:
                    if tup2[5] is None:
                        val2 = None
                    else:
                        #Use the covalent radius
                        val2 = tup1[5]
                else:
                    val2 = tup2[attrindex]
                if val1 is not None and val2 is not None:
                    m[-1].append( f * (val1 + val2))
                else:
                    #If no radius is found for either atom, set tolerance to None
                    m[-1].append(None)
        self.matrix = np.array(m)
        """A symmetric numpy matrix storing the tolerance between specie pairs."""
        self.custom_values = []
        """A list of tuples storing which species pair tolerances have custom values."""

        try:
            for tup in tuples:
                self.set_tol(*tup)
        except:
            print("Error: Could not set custom tolerance value(s).")
            print("    All custom entries should be entered using the following form:")
            print("    (specie1, specie2, value), where value is the tolerance in Angstroms.")

        self.radius_list = []
        for i in range(len(self.matrix)):
            if i == 0: continue
            x = self.get_tol(i, i)
            self.radius_list.append(x)

    def get_tol(self, specie1, specie2):
        """
        Returns the tolerance between two species.
        
        Args:
            specie1, specie2: the atomic number (int or float), name (str), symbol (str),
                an Element object, or a pymatgen Specie object

        Returns:
            the tolerance between the provided pair of atomic species
        """
        if self.prototype == "single_value":
            return self.matrix[0][0]
        index1 = Element.number_from_specie(specie1)
        index2 = Element.number_from_specie(specie2)
        if index1 is not None and index2 is not None:
            return self.matrix[index1][index2]
        else:
            return None

    def set_tol(self, specie1, specie2, value):
        """
        Sets the distance tolerance between two species.
        
        Args:
            specie1, specie2: the atomic number (int or float), name (str), symbol (str),
                an Element object, or a pymatgen Specie object
            value:
                the tolerance (in Angstroms) to set to
        """
        index1 = Element.number_from_specie(specie1)
        index2 = Element.number_from_specie(specie2)
        if index1 is None or index2 is None:
            return
        self.matrix[index1][index2] = float(value)
        if index1 != index2:
            self.matrix[index2][index1] = float(value)
        if (index1, index2) not in self.custom_values and (index2, index1) not in self.custom_values:
            larger = max(index1, index2)
            smaller = min(index1, index2)
            self.custom_values.append((smaller, larger))

    def from_matrix(matrix, prototype="atomic", factor=1.0, begin_with=0):
        """
        Given a tolerance matrix, returns a Tol_matrix object. Matrix indices correspond to
        the atomic number (with 0 pointing to Hydrogen by default). For atoms with atomic
        numbers not included in the matrix, the default value (specified by prototype) will be
        used, up to element 96. Note that if the matrix is asymmetric, only the value below the
        diagonal will be used.

        Args:
            matrix: a 2D matrix or list of tolerances between atomic species pairs. The
                indices correspond to atomic species (see begin_with variable description)
            prototype: a string representing the type of radii to use
                ("atomic", "molecular")
            factor: a float to scale the distances by. A smaller value means a smaller
                tolerance for distance checking
            begin_with: the index which points to Hydrogen within the matrix. Default 0

        Returns:
            a Tol_matrix object
        """
        m = np.array(matrix)
        tups = []
        for i, row in enumerate(matrix):
            for j, value in enumerate(row):
                if j > i: continue
                tups.append( (i+1-begin_with, j+1-begin_with, matrix[i][j]) )
        tm = Tol_matrix(prototype=prototype, factor=factor, *tups)
        return tm

    def from_radii(radius_list, prototype="atomic", factor=1.0, begin_with=0):
        """
        Given a list of atomic radii, returns a Tol_matrix object. For atom-atom pairs, uses
        the average radii of the two species as the tolerance value. For atoms with atomic
        numbers not in the radius list, the default value (specified by prototype) will be
        used, up to element 96.

        Args:
            radius_list: a list of atomic radii (in Angstroms), beginning with Hydrogen
            prototype: a string representing the type of radii to use
                ("atomic", "molecular")
            factor: a float to scale the distances by. A smaller value means a smaller
                tolerance for distance checking
            begin_with: the index which points to Hydrogen within the list. Default 0

        Returns:
            a Tol_matrix object
        """
        tups = []
        f = factor * 0.5
        for i, r1 in enumerate(radius_list):
            for j, r2 in enumerate(radius_list):
                if j > i: continue
                tups.append( (i+1-begin_with, j+1-begin_with, f*(r1+r2)) )
        tm = Tol_matrix(prototype=prototype, factor=factor, *tups)
        return tm

    def from_single_value(value):
        """
        Creates a Tol_matrix which only has a single tolerance value. Using get_tol will
        always return the same value.

        Args:
            value: the tolerance value to use

        Returns:
            a Tol_matrix object whose methods are overridden to use a single tolerance value
        """
        tm = Tol_matrix()
        tm.prototype = "single value"
        tm.matrix = np.array([[value]])
        tm.custom_values = [(1,1)]
        tm.radius_type = "N/A"
        return tm

    def __getitem__(self, index):
        new_index = Element.number_from_specie(index)
        return self.matrix[index]

    def print_all(self):
        print("--Tol_matrix class object--")
        print("  Prototype: "+str(self.prototype))
        print("  Atomic radius type: "+str(self.radius_type))
        print("  Radius scaling factor: "+str(self.f))
        if self.prototype == "single value":
            print("  Custom tolerance value: "+str(self.matrix([0][0])))
        else:
            if self.custom_values == []:
                print("  Custom tolerance values: None")
            else:
                print("  Custom tolerance values:")
                for tup in self.custom_values:
                    print("    "+str(Element(tup[0]).short_name)+", "+str(Element(tup[1]).short_name)+": "+str(self.get_tol(tup[0],tup[1])))

    def to_file(self, filename=None):
        """
        Creates a file with the given filename and file type to store the structure.
        By default, creates cif files for crystals and xyz files for clusters.
        By default, the filename is based on the stoichiometry.

        Args:
            fmt: the file type ('cif', 'xyz', etc.)
            filename: the file path

        Returns:
            Nothing. Creates a file at the specified path
        """
        if filename == None:
            given = False
        else:
            given = True
        if filename == None:
            filename = "custom_tol_matrix"
        #Check if filename already exists
        #If it does, add a new number to end of filename
        if exists(filename):
            i = 1
            while True:
                outdir = filename + "_" + str(i)
                if not exists(outdir):
                    break
                i += 1
                if i > 10000:
                    return "Could not create file: too many files already created."
        else:
            outdir = filename
        try:
            np.save(filename, [self])
            return "Output file to " + outdir + ".npy"
        except:
            return "Error: Could not save Tol_matrix to file."

    def from_file(filename):
        try:
            tm = np.load(filename)[0]
            if type(tm) == Tol_matrix:
                return tm
            else:
                print("Error: invalid file for Tol_matrix.")
                return
        except:
            print("Error: Could not load Tol_matrix from file.")
            return

def gaussian(min, max, sigma=3.0):
    """
    Choose a random number from a Gaussian probability distribution centered
    between min and max. sigma is the number of standard deviations that min
    and max are away from the center. Thus, sigma is also the largest possible
    number of standard deviations corresponding to the returned value. sigma=2
    corresponds to a 95.45% probability of choosing a number between min and
    max.

    Args:
        min: the minimum acceptable value
        max: the maximum acceptable value
        sigma: the number of standard deviations between the center and min or max

    Returns:
        a value chosen randomly between min and max
    """
    center = (max+min)*0.5
    delta = fabs(max-min)*0.5
    ratio = delta/sigma
    while True:
        x = np.random.normal(scale=ratio, loc=center)
        if x > min and x < max:
            return x

def get_tol(specie):
    """
    Given an atomic specie name, return the covalent radius.
    
    Args:
        specie: a string for the atomic symbol

    Returns:
        the covalent radius in Angstroms
    """
    return Element(specie).covalent_radius

tols_from_species = np.vectorize(get_tol)
"""
Given a list of atomic species names, returns a list of
covalent radii

Args:
    species: a list of strings for atomic species names or symbols

Returns:
    A 1D numpy array of distances in Angstroms
"""

def check_distance(coord1, coord2, species1, species2, lattice, PBC=[1,1,1], tm=Tol_matrix(prototype="atomic"), d_factor=1.0):
    """
    Check the distances between two set of atoms. Distances between coordinates
    within the first set are not checked, and distances between coordinates within
    the second set are not checked. Only distances between points from different
    sets are checked.

    Args:
        coord1: a list of fractional coordinates e.g. [[.1,.6,.4]
            [.3,.8,.2]]
        coord2: a list of new fractional coordinates e.g. [[.7,.8,.9],
            [.4,.5,.6]]
        species1: a list of atomic species or numbers for coord1
        species2: a list of atomic species or numbers for coord2
        lattice: matrix describing the unit cell vectors
        PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
            Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis
        tm: a Tol_matrix object, or a string representing the type of Tol_matrix
            to use
        d_factor: the tolerance is multiplied by this amount. Larger values
            mean atoms must be farther apart

    Returns:
        a bool for whether or not the atoms are sufficiently far enough apart
    """
    #Check that there are points to compare
    if len(coord1) <= 1 or len(coord2) <= 1:
        return True

    #Create tolerance matrix from subset of tm
    tols = np.zeros((len(species1),len(species2)))
    for i1, specie1 in enumerate(species1):
        for i2, specie2 in enumerate(species2):
            tols[i1][i2] = tm.get_tol(specie1, specie2)

    #Calculate the distance between each i, j pair
    d = distance_matrix(coord1, coord2, lattice, PBC=PBC)

    #Check if the distance is ever less than the tolerance
    if (d < tols).sum() > 0:
        return False
    else:
        return True

def check_images(coords, species, lattice, PBC=[1,1,1], tm=Tol_matrix(prototype="atomic"), d_factor=1.0):
    """
    Given a set of (unfiltered) fractional coordinates, checks if the periodic images are too close.
    
    Args:
        coords: a list of fractional coordinates
        species: the atomic species of each coordinate
        lattice: a 3x3 lattice matrix
        PBC: the periodic boundary conditions
        tm: a Tol_matrix object
        d_factor: the tolerance is multiplied by this amount. Larger values
            mean atoms must be farther apart

    Returns:
        False if distances are too close. True if distances are not too close
    """
    coords = np.array(coords)
    m = create_matrix(PBC=PBC)
    new_coords = []
    new_species = []
    for v in m:
        if v[0] == 0 and v[1] == 0 and v[2] == 0: continue
        for v2 in coords+v:
            new_coords.append(v2)
        new_species += species
    return check_distance(coords, np.array(new_coords), species, new_species, lattice, PBC=[0,0,0], tm=tm, d_factor=d_factor)

def get_center(xyzs, lattice, PBC=[1,1,1]):
    """
    Finds the geometric centers of the clusters under periodic boundary
    conditions.

    Args:
        xyzs: a list of fractional coordinates
        lattice: a matrix describing the unit cell
        PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
            Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis

    Returns:
        x,y,z coordinates for the center of the input coordinate list
    """
    matrix0 = create_matrix(PBC=PBC)
    xyzs -= np.round(xyzs)
    matrix_min = [0,0,0]
    for atom1 in range(1,len(xyzs)):
        dist_min = 10.0
        for atom2 in range(0, atom1):
            #shift atom1 to position close to atom2
            matrix = matrix0 + (xyzs[atom1] - xyzs[atom2])
            matrix = np.dot(matrix, lattice)
            dists = cdist(matrix, [[0,0,0]])
            if np.min(dists) < dist_min:
                dist_min = np.min(dists)
                matrix_min = matrix0[np.argmin(dists)]
        xyzs[atom1] += matrix_min
    center = xyzs.mean(0)
    return center

def para2matrix(cell_para, radians=True, format='lower'):
    """
    Given a set of lattic parameters, generates a matrix representing the
    lattice vectors

    Args:
        cell_para: a 1x6 list of lattice parameters [a, b, c, alpha, beta,
            gamma]. a, b, and c are the length of the lattice vectos, and
            alpha, beta, and gamma are the angles between these vectors. Can
            be generated by matrix2para
        radians: if True, lattice parameters should be in radians. If False,
            lattice angles should be in degrees
        format: a string ('lower', 'symmetric', or 'upper') for the type of
            matrix to be output

    Returns:
        a 3x3 matrix representing the unit cell. By default (format='lower'),
        the a vector is aligined along the x-axis, and the b vector is in the
        y-z plane
    """
    a = cell_para[0]
    b = cell_para[1]
    c = cell_para[2]
    alpha = cell_para[3]
    beta = cell_para[4]
    gamma = cell_para[5]
    if radians is not True:
        rad = pi/180.
        alpha *= rad
        beta *= rad
        gamma *= rad
    cos_alpha = np.cos(alpha)
    cos_beta = np.cos(beta)
    cos_gamma = np.cos(gamma)
    sin_gamma = np.sin(gamma)
    sin_alpha = np.sin(alpha)
    matrix = np.zeros([3,3])
    if format == 'lower':
        #Generate a lower-diagonal matrix
        c1 = c*cos_beta
        c2 = (c*(cos_alpha - (cos_beta * cos_gamma))) / sin_gamma
        matrix[0][0] = a
        matrix[1][0] = b * cos_gamma
        matrix[1][1] = b * sin_gamma
        matrix[2][0] = c1
        matrix[2][1] = c2
        matrix[2][2] = sqrt(c**2 - c1**2 - c2**2)
    elif format == 'symmetric':
        #TODO: allow generation of symmetric matrices
        pass
    elif format == 'upper':
        #Generate an upper-diagonal matrix
        a3 = a*cos_beta
        a2 = (a*(cos_gamma - (cos_beta * cos_alpha))) / sin_alpha
        matrix[2][2] = c
        matrix[1][2] = b * cos_alpha
        matrix[1][1] = b * sin_alpha
        matrix[0][2] = a3
        matrix[0][1] = a2
        matrix[0][0] = sqrt(a**2 - a3**2 - a2**2)
        pass
    return matrix

def Add_vacuum(lattice, coor, vacuum=10, PBC=[0,0,0]):
    """
    Adds space above and below a 2D or 1D crystal. This allows for treating the
    structure as a 3D crystal during energy optimization

    Args:
        lattice: the lattice matrix of the crystal
        coor: the relative coordinates of the crystal
        vacuum: the amount of space, in Angstroms, to add above and below
        PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
            Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis

    Returns:
        lattice, coor: The transformed lattice and coordinates after the
            vacuum space is added
    """
    absolute_coords = np.dot(coor, lattice)
    for i, a in enumerate(PBC):
        if not a:
            lattice[i] += (lattice[i]/np.linalg.norm(lattice[i])) * vacuum
    new_coor = np.dot(absolute_coords, np.linalg.inv(lattice))
    return lattice, new_coor

def Permutation(lattice, coor, PB):
    """
    Permutes a list of coordinates. Not currently implemented.
    """
    para = matrix2para(lattice)
    para1 = deepcopy(para)
    coor1 = deepcopy(coor)
    for axis in [0,1,2]:
        para1[axis] = para[PB[axis]-1]
        para1[axis+3] = para[PB[axis]+2]
        coor1[:,axis] = coor[:,PB[axis]-1]
    return para2matrix(para1), coor1

def matrix2para(matrix, radians=True):
    """
    Given a 3x3 matrix representing a unit cell, outputs a list of lattice
    parameters.

    Args:
        matrix: a 3x3 array or list, where the first, second, and third rows
            represent the a, b, and c vectors respectively
        radians: if True, outputs angles in radians. If False, outputs in
            degrees

    Returns:
        a 1x6 list of lattice parameters [a, b, c, alpha, beta, gamma]. a, b,
        and c are the length of the lattice vectos, and alpha, beta, and gamma
        are the angles between these vectors (in radians by default)
    """
    cell_para = np.zeros(6)
    #a
    cell_para[0] = np.linalg.norm(matrix[0])
    #b
    cell_para[1] = np.linalg.norm(matrix[1])
    #c
    cell_para[2] = np.linalg.norm(matrix[2])
    #alpha
    cell_para[3] = angle(matrix[1], matrix[2])
    #beta
    cell_para[4] = angle(matrix[0], matrix[2])
    #gamma
    cell_para[5] = angle(matrix[0], matrix[1])
    
    if not radians:
        #convert radians to degrees
        deg = 180./pi
        cell_para[3] *= deg
        cell_para[4] *= deg
        cell_para[5] *= deg
    return cell_para

def cellsize(group, dim=3):
    """
    Returns the number of duplicate atoms in the conventional lattice (in
    contrast to the primitive cell). Based on the type of cell centering (P,
    A, C, I, R, or F)

    Args:
        group: a Group object, or the space group number of the group
        dim: the dimension of the group (3 for space group, 2 for layer group,
            1 for Rod group, or 0 for 3D point group). If group is a Group
            object, dim will be overridden by group's value for dim
    
    Returns:
        an integer between 1 and 4, telling how many atoms are in the conventional cell
    """
    #Get the group dimension and number
    if type(group) == Group:
        num = group.number
        dim = group.dim
    elif type(int(group)) == int:
        num = group
    if dim == 0 or dim == 1:
        #Rod and point groups
        return 1
    elif dim == 2:
        #Layer groups
        if num in [10, 13, 18, 22, 26, 35, 36, 47, 48]:
            return 2
        else:
            return 1
    elif dim == 3:
        #space groups
        if num in [22, 42, 43, 69, 70, 196, 202, 203, 209, 210, 216, 219, 225, 226, 227, 228]:
            return 4 #F
        elif num in [146, 148, 155, 160, 161, 166, 167]:
            return 3 #R
        elif num in [5, 8, 9, 12, 15, 20, 21, 23, 24, 35, 36, 37,  38, 39, 40, 41,  44, 45, 46, 63, 64, 65, 66, 67, 68, 71, 72, 73, 74, 79, 80, 82, 87, 88, 97, 98, 107, 108, 109, 110, 119, 120, 121, 122, 139, 140, 141, 142, 197, 199, 204, 206, 211, 214, 217, 220, 229, 230]:
            return 2 #A, C, I
        else:
            return 1 #P

def find_short_dist(coor, lattice, tol, PBC=[1,1,1]):
    """
    Given a list of fractional coordinates, finds pairs which are closer
    together than tol, and builds the connectivity map

    Args:
        coor: a list of fractional 3-dimensional coordinates
        lattice: a matrix representing the crystal unit cell
        tol: the distance tolerance for pairing coordinates
        PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
            Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis
    
    Returns:
        pairs, graph: (pairs) is a list whose entries have the form [index1,
        index2, distance], where index1 and index2 correspond to the indices
        of a pair of points within the supplied list (coor). distance is the
        distance between the two points. (graph) is a connectivity map in the
        form of a list. Its first index represents a point within coor, and
        the second indices represent which point(s) it is connected to.
    """
    pairs=[]
    graph=[]
    for i in range(len(coor)):
        graph.append([])

    d = distance_matrix(coor, coor, lattice, PBC=PBC)
    ijs = np.where(d<= tol)
    for i in np.unique(ijs[0]):
        j = ijs[1][i]
        if j <= i: continue
        pairs.append([i, j, d[i][j]])

    pairs = np.array(pairs)
    if len(pairs) > 0:
        d_min = min(pairs[:,-1]) + 1e-3
        sequence = [pairs[:,-1] <= d_min]
        #Avoid Futurewarning
        #pairs1 = deepcopy(pairs)
        #pairs = pairs1[sequence]
        pairs = pairs[tuple(sequence)]
        for pair in pairs:
            pair0=int(pair[0])
            pair1=int(pair[1])
            graph[pair0].append(pair1)
            graph[pair1].append(pair0)

    return pairs, graph

def connected_components(graph):
    """
    Given an undirected graph (a 2d array of indices), return a set of
    connected components, each connected component being an (arbitrarily
    ordered) array of indices which are connected either directly or
    indirectly.

    Args:
        graph: a list reprenting the connections between points. The first index
            represents a point, and the 2nd indices represent the points to
            which the first point is connected. Can be generated by
            find_short_dist

    Returns:
        a list of connected components. The first index denotes a separate
        connected component. The second indices denote the points within the
        connected component which are connected to each other
    """
    def add_neighbors(el, seen=[]):
        """
        Find all elements which are connected to el. Return an array which
        includes these elements and el itself.
        """
        #seen stores already-visited indices
        if seen == []: seen = [el]
        #iterate through the neighbors (x) of el
        for x in graph[el]:
            if x not in seen:
                seen.append(x)
                #Recursively find neighbors of x
                add_neighbors(x, seen)
        return seen

    #Create a list of indices to iterate through
    unseen = list(range(len(graph)))
    sets = []
    i = 0
    while (unseen != []):
        #x is the index we are finding the connected component of
        x = unseen.pop()
        sets.append([])
        #Add neighbors of x to the current connected component
        for y in add_neighbors(x):
            sets[i].append(y)
            #Remove indices which have already been found
            if y in unseen: unseen.remove(y)
        i += 1
    return sets

def merge_coordinate(coor, lattice, group, tol):
    """
    Given a list of fractional coordinates, merges them within a given
    tolerance, and checks if the merged coordinates satisfy a Wyckoff
    position. Used for merging general Wyckoff positions into special Wyckoff
    positions within the random_crystal (and its derivative) classes.

    Args:
        coor: a list of fractional coordinates
        lattice: a 3x3 matrix representing the unit cell
        group: a pyxtal.symmetry.Group object
        tol: the cutoff distance for merging coordinates

    Returns:
        coor, index, point: (coor) is the new list of fractional coordinates after
        merging. index is a single index for the Wyckoff position within
        the sg. If no matching WP is found, returns False. point is a 3-vector;
        when plugged into the Wyckoff position, it will generate all the other
        points.
    """
    wyckoffs = group.wyckoffs
    PBC = group.PBC
    while True:
        pairs, graph = find_short_dist(coor, lattice, tol, PBC=PBC)
        index = None
        if len(pairs)>0:
            if len(coor) > len(wyckoffs[-1]):
                merged = []
                components = connected_components(graph)
                for c in components:
                    merged.append(get_center(coor[c], lattice, PBC=PBC))
                merged = np.array(merged)
                index, point = check_wyckoff_position(merged, group)
                if index is False:
                    return coor, False, None
                else:
                    coor = merged

            else:#no way to merge
                return coor, False, None
        else:
            if index is None:
                index, point = check_wyckoff_position(coor, group)
            return coor, index, point

def estimate_volume(numIons, species, factor=1.0):
    """
    Estimates the volume of a unit cell based on the number and types of ions.
    Assumes each atom takes up a sphere with radius equal to its covalent bond
    radius.

    Args:
        numIons: a list of the number of ions for each specie
        species: a corresponding list for the specie of each type of ion. Each
            element in the list should be a string for the atomic symbol
        factor: an optional factor to multiply the result by. Larger values
            allow more space between atoms
    
    Returns:
        a float value for the estimated volume
    """
    volume = 0
    for numIon, specie in zip(numIons, species):
        r = rand_u(Element(specie).covalent_radius, Element(specie).vdw_radius)
        volume += numIon*4/3*pi*r**3
    return factor*volume

def generate_lattice(ltype, volume, minvec=tol_m, minangle=pi/6, max_ratio=10.0, maxattempts = 100, **kwargs):
    """
    Generates a lattice (3x3 matrix) according to the space group symmetry and
    number of atoms. If the spacegroup has centering, we will transform to
    conventional cell setting. If the generated lattice does not meet the
    minimum angle and vector requirements, we try to generate a new one, up to
    maxattempts times.

    Args:
        sg: International number of the space group
        volume: volume of the conventional unit cell
        minvec: minimum allowed lattice vector length (among a, b, and c)
        minangle: minimum allowed lattice angle (among alpha, beta, and gamma)
        max_ratio: largest allowed ratio of two lattice vector lengths
        maxattempts: the maximum number of attempts for generating a lattice
        kwargs: a dictionary of optional values. These include:
            'unique_axis': the axis ('a', 'b', or 'c') which is not symmetrically
                equivalent to the other two
            'min_l': the smallest allowed cell vector. The smallest vector must be larger
                than this.
            'mid_l': the second smallest allowed cell vector. The second smallest vector
                must be larger than this.
            'max_l': the third smallest allowed cell vector. The largest cell vector must
                be larger than this.

    Returns:
        a 3x3 matrix representing the lattice vectors of the unit cell. If
        generation fails, outputs a warning message and returns empty
    """
    maxangle = pi-minangle
    for n in range(maxattempts):
        #Triclinic
        #if sg <= 2:
        if ltype == "triclinic":
            #Derive lattice constants from a random matrix
            mat = random_shear_matrix(width=0.2)
            a, b, c, alpha, beta, gamma = matrix2para(mat)
            x = sqrt(1-cos(alpha)**2 - cos(beta)**2 - cos(gamma)**2 + 2*(cos(alpha)*cos(beta)*cos(gamma)))
            vec = random_vector()
            abc = volume/x
            xyz = vec[0]*vec[1]*vec[2]
            a = vec[0]*np.cbrt(abc)/np.cbrt(xyz)
            b = vec[1]*np.cbrt(abc)/np.cbrt(xyz)
            c = vec[2]*np.cbrt(abc)/np.cbrt(xyz)
        #Monoclinic
        #elif sg <= 15:
        elif ltype == "monoclinic":
            alpha, gamma  = pi/2, pi/2
            beta = gaussian(minangle, maxangle)
            x = sin(beta)
            vec = random_vector()
            xyz = vec[0]*vec[1]*vec[2]
            abc = volume/x
            a = vec[0]*np.cbrt(abc)/np.cbrt(xyz)
            b = vec[1]*np.cbrt(abc)/np.cbrt(xyz)
            c = vec[2]*np.cbrt(abc)/np.cbrt(xyz)
        #Orthorhombic
        #elif sg <= 74:
        elif ltype == "orthorhombic":
            alpha, beta, gamma = pi/2, pi/2, pi/2
            x = 1
            vec = random_vector()
            xyz = vec[0]*vec[1]*vec[2]
            abc = volume/x
            a = vec[0]*np.cbrt(abc)/np.cbrt(xyz)
            b = vec[1]*np.cbrt(abc)/np.cbrt(xyz)
            c = vec[2]*np.cbrt(abc)/np.cbrt(xyz)
        #Tetragonal
        #elif sg <= 142:
        elif ltype == "tetragonal":
            alpha, beta, gamma = pi/2, pi/2, pi/2
            x = 1
            vec = random_vector()
            c = vec[2]/(vec[0]*vec[1])*np.cbrt(volume/x)
            a = b = sqrt((volume/x)/c)
        #Trigonal/Rhombohedral/Hexagonal
        #elif sg <= 194:
        elif ltype == "hexagonal":
            alpha, beta, gamma = pi/2, pi/2, pi/3*2
            x = sqrt(3.)/2.
            vec = random_vector()
            c = vec[2]/(vec[0]*vec[1])*np.cbrt(volume/x)
            a = b = sqrt((volume/x)/c)
        #Cubic
        #else:
        elif ltype == "cubic":
            alpha, beta, gamma = pi/2, pi/2, pi/2
            s = (volume) ** (1./3.)
            a, b, c = s, s, s
        #Check that lattice meets requirements
        maxvec = (a*b*c)/(minvec**2)

        #Define limits on cell dimensions
        if 'min_l' not in kwargs:
            min_l = minvec
        else:
            min_l = kwargs['min_l']
        if 'mid_l' not in kwargs:
            mid_l = min_l
        else:
            mid_l = kwargs['mid_l']
        if 'max_l' not in kwargs:
            max_l = mid_l
        else:
            max_l = kwargs['max_l']
        l_min = min(a, b, c)
        l_max = max(a, b, c)
        for x in (a, b, c):
            if x <= l_max and x >= l_min:
                l_mid = x
        if not (l_min >= min_l and l_mid >= mid_l and l_max >= max_l):
            continue

        if minvec < maxvec:
            #Check minimum Euclidean distances
            smallvec = min(a*cos(max(beta, gamma)), b*cos(max(alpha, gamma)), c*cos(max(alpha, beta)))
            if(a>minvec and b>minvec and c>minvec
            and a<maxvec and b<maxvec and c<maxvec
            and smallvec < minvec
            and alpha>minangle and beta>minangle and gamma>minangle
            and alpha<maxangle and beta<maxangle and gamma<maxangle
            and a/b<max_ratio and a/c<max_ratio and b/c<max_ratio
            and b/a<max_ratio and c/a<max_ratio and c/b<max_ratio):
                return np.array([a, b, c, alpha, beta, gamma])
    #If maxattempts tries have been made without success
    print("Error: Could not generate lattice after "+str(n+1)+" attempts for volume ", volume)
    return

def generate_lattice_2D(ltype, volume, thickness=None, minvec=tol_m, minangle=pi/6, max_ratio=10.0, maxattempts = 100, **kwargs):
    """
    Generates a lattice (3x3 matrix) according to the spacegroup symmetry and
    number of atoms. If the layer group has centering, we will use the
    conventional cell setting. If the generated lattice does not meet the
    minimum angle and vector requirements, we try to generate a new one, up to
    maxattempts times.
    Note: The monoclinic layer groups have different unique axes. Groups 3-7
        have unique axis c, while 8-18 have unique axis a. We use non-periodic
        axis c for all layer groups.

    Args:
        num: International number of the space group
        volume: volume of the lattice
        thickness: 3rd-dimensional thickness of the unit cell. If set to None,
            a thickness is chosen automatically
        minvec: minimum allowed lattice vector length (among a, b, and c)
        minangle: minimum allowed lattice angle (among alpha, beta, and gamma)
        max_ratio: largest allowed ratio of two lattice vector lengths
        maxattempts: the maximum number of attempts for generating a lattice
        kwargs: a dictionary of optional values. These include:
            'unique_axis': the axis ('a', 'b', or 'c') which is not symmetrically
                equivalent to the other two
            'min_l': the smallest allowed cell vector. The smallest vector must be larger
                than this.
            'mid_l': the second smallest allowed cell vector. The second smallest vector
                must be larger than this.
            'max_l': the third smallest allowed cell vector. The largest cell vector must
                be larger than this.

    Returns:
        a 3x3 matrix representing the lattice vectors of the unit cell. If
        generation fails, outputs a warning message and returns empty
    """
    if 'unique_axis' not in kwargs:
        unique_axis = "c"
    else:
        unique_axis = kwargs['unique_axis']
    #Store the non-periodic axis
    NPA = 3
    #Set the unique axis for monoclinic cells
    #if num in range(3, 8): unique_axis = "c"
    #elif num in range(8, 19): unique_axis = "a"
    maxangle = pi-minangle
    for n in range(maxattempts):
        abc = np.ones([3])
        if thickness is None:
            v = random_vector()
            thickness1 = np.cbrt(volume)*(v[0]/(v[0]*v[1]*v[2]))
        else:
            thickness1 = thickness
        abc[NPA-1] = thickness1
        alpha, beta, gamma  = pi/2, pi/2, pi/2
        #Triclinic
        #if num <= 2:
        if ltype == "triclinic":
            mat = random_shear_matrix(width=0.2)
            a, b, c, alpha, beta, gamma = matrix2para(mat)
            x = sqrt(1-cos(alpha)**2 - cos(beta)**2 - cos(gamma)**2 + 2*(cos(alpha)*cos(beta)*cos(gamma)))
            abc[NPA-1] = abc[NPA-1]/x #scale thickness by outer product of vectors
            ab = volume/(abc[NPA-1]*x)
            ratio = a/b
            if NPA == 3:
                abc[0] = sqrt(ab*ratio)
                abc[1] = sqrt(ab/ratio)
            elif NPA == 2:
                abc[0] = sqrt(ab*ratio)
                abc[2] = sqrt(ab/ratio)
            elif NPA == 1:
                abc[1] = sqrt(ab*ratio)
                abc[2] = sqrt(ab/ratio)

        #Monoclinic
        #elif num <= 18:
        elif ltype == "monoclinic":
            a, b, c = random_vector()
            if unique_axis == "a":
                alpha = gaussian(minangle, maxangle)
                x = sin(alpha)
            elif unique_axis == "b":
                beta = gaussian(minangle, maxangle)
                x = sin(beta)
            elif unique_axis == "c":
                gamma = gaussian(minangle, maxangle)
                x = sin(gamma)
            ab = volume/(abc[NPA-1]*x)
            ratio = a/b
            if NPA == 3:
                abc[0] = sqrt(ab*ratio)
                abc[1] = sqrt(ab/ratio)
            elif NPA == 2:
                abc[0] = sqrt(ab*ratio)
                abc[2] = sqrt(ab/ratio)
            elif NPA == 1:
                abc[1] = sqrt(ab*ratio)
                abc[2] = sqrt(ab/ratio)

        #Orthorhombic
        #elif num <= 48:
        elif ltype == "orthorhombic":
            vec = random_vector()
            if NPA == 3:
                ratio = abs(vec[0]/vec[1]) #ratio a/b
                abc[1] = sqrt(volume/(thickness1*ratio))
                abc[0] = abc[1]* ratio
            elif NPA == 2:
                ratio = abs(vec[0]/vec[2]) #ratio a/b
                abc[2] = sqrt(volume/(thickness1*ratio))
                abc[0] = abc[2]* ratio
            elif NPA == 1:
                ratio = abs(vec[1]/vec[2]) #ratio a/b
                abc[2] = sqrt(volume/(thickness1*ratio))
                abc[1] = abc[2]* ratio

        #Tetragonal
        #elif num <= 64:
        elif ltype == "tetragonal":
            if NPA == 3:
                abc[0] = abc[1] = sqrt(volume/thickness1)
            elif NPA == 2:
                abc[0] = abc[1]
                abc[2] = volume/(abc[NPA-1]**2)
            elif NPA == 1:
                abc[1] = abc[0]
                abc[2] = volume/(abc[NPA-1]**2)

        #Trigonal/Rhombohedral/Hexagonal
        #elif num <= 80:
        elif ltype == "hexagonal":
            gamma = pi/3*2
            x = sqrt(3.)/2.
            if NPA == 3:
                abc[0] = abc[1] = sqrt((volume/x)/abc[NPA-1])
            elif NPA == 2:
                abc[0] = abc[1]
                abc[2] = (volume/x)(thickness1**2)
            elif NPA == 1:
                abc[1] = abc[0]
                abc[2] = (volume/x)/(thickness1**2)

        para = np.array([abc[0], abc[1], abc[2], alpha, beta, gamma])

        a, b, c = abc[0], abc[1], abc[2]
        maxvec = (a*b*c)/(minvec**2)

        #Define limits on cell dimensions
        if 'min_l' not in kwargs:
            min_l = minvec
        else:
            min_l = kwargs['min_l']
        if 'mid_l' not in kwargs:
            mid_l = min_l
        else:
            mid_l = kwargs['mid_l']
        if 'max_l' not in kwargs:
            max_l = mid_l
        else:
            max_l = kwargs['max_l']
        l_min = min(a, b, c)
        l_max = max(a, b, c)
        for x in (a, b, c):
            if x <= l_max and x >= l_min:
                l_mid = x
        if not (l_min >= min_l and l_mid >= mid_l and l_max >= max_l):
            continue

        if minvec < maxvec:
            smallvec = min(a*cos(max(beta, gamma)), b*cos(max(alpha, gamma)), c*cos(max(alpha, beta)))
            if(a>minvec and b>minvec and c>minvec
            and a<maxvec and b<maxvec and c<maxvec
            and smallvec < minvec
            and alpha>minangle and beta>minangle and gamma>minangle
            and alpha<maxangle and beta<maxangle and gamma<maxangle
            and a/b<max_ratio and a/c<max_ratio and b/c<max_ratio
            and b/a<max_ratio and c/a<max_ratio and c/b<max_ratio):
                return para

    #If maxattempts tries have been made without success
    print("Error: Could not generate lattice after "+str(n+1)+" attempts")
    return

def generate_lattice_1D(ltype, volume, area=None, minvec=tol_m, minangle=pi/6, max_ratio=10.0, maxattempts = 100, **kwargs):
    """
    Generates a lattice (3x3 matrix) according to the spacegroup symmetry and
    number of atoms. If the spacegroup has centering, we will transform to
    conventional cell setting. If the generated lattice does not meet the
    minimum angle and vector requirements, we try to generate a new one, up to
    maxattempts times.
    Note: The monoclinic Rod groups have different unique axes. Groups 3-7
        have unique axis a, while 8-12 have unique axis c. We use periodic
        axis c for all Rod groups.

    Args:
        num: number of the Rod group
        volume: volume of the lattice
        area: cross-sectional area of the unit cell in Angstroms squared. If
            set to None, a value is chosen automatically
        minvec: minimum allowed lattice vector length (among a, b, and c)
        minangle: minimum allowed lattice angle (among alpha, beta, and gamma)
        max_ratio: largest allowed ratio of two lattice vector lengths
        maxattempts: the maximum number of attempts for generating a lattice
        kwargs: a dictionary of optional values. These include:
            'unique_axis': the axis ('a', 'b', or 'c') which is not symmetrically
                equivalent to the other two
            'min_l': the smallest allowed cell vector. The smallest vector must be larger
                than this.
            'mid_l': the second smallest allowed cell vector. The second smallest vector
                must be larger than this.
            'max_l': the third smallest allowed cell vector. The largest cell vector must
                be larger than this.

    Returns:
        a 3x3 matrix representing the lattice vectors of the unit cell. If
        generation fails, outputs a warning message and returns empty
    """
    try:
        unique_axis = kwargs['unique_axis']
    except:
        unique_axis = "a"
    #Store the periodic axis
    PA = 3
    #Set the unique axis for monoclinic cells
    #if num in range(3, 8): unique_axis = "a"
    #elif num in range(8, 13): unique_axis = "c"
    maxangle = pi-minangle
    for n in range(maxattempts):
        abc = np.ones([3])
        if area is None:
            v = random_vector()
            thickness1 = np.cbrt(volume)*(v[0]/(v[0]*v[1]*v[2]))
        else:
            thickness1 = volume/area
        abc[PA-1] = thickness1
        alpha, beta, gamma  = pi/2, pi/2, pi/2
        #Triclinic
        #if num <= 2:
        if ltype == "triclinic":
            mat = random_shear_matrix(width=0.2)
            a, b, c, alpha, beta, gamma = matrix2para(mat)
            x = sqrt(1-cos(alpha)**2 - cos(beta)**2 - cos(gamma)**2 + 2*(cos(alpha)*cos(beta)*cos(gamma)))
            abc[PA-1] = abc[PA-1]/x #scale thickness by outer product of vectors
            ab = volume/(abc[PA-1]*x)
            ratio = a/b
            if PA == 3:
                abc[0] = sqrt(ab*ratio)
                abc[1] = sqrt(ab/ratio)
            elif PA == 2:
                abc[0] = sqrt(ab*ratio)
                abc[2] = sqrt(ab/ratio)
            elif PA == 1:
                abc[1] = sqrt(ab*ratio)
                abc[2] = sqrt(ab/ratio)

        #Monoclinic
        #elif num <= 12:
        elif ltype == "monoclinic":
            a, b, c = random_vector()
            if unique_axis == "a":
                alhpa = gaussian(minangle, maxangle)
                x = sin(alpha)
            elif unique_axis == "b":
                beta = gaussian(minangle, maxangle)
                x = sin(beta)
            elif unique_axis == "c":
                gamma = gaussian(minangle, maxangle)
                x = sin(gamma)
            ab = volume/(abc[PA-1]*x)
            ratio = a/b
            if PA == 3:
                abc[0] = sqrt(ab*ratio)
                abc[1] = sqrt(ab/ratio)
            elif PA == 2:
                abc[0] = sqrt(ab*ratio)
                abc[2] = sqrt(ab/ratio)
            elif PA == 1:
                abc[1] = sqrt(ab*ratio)
                abc[2] = sqrt(ab/ratio)

        #Orthorhombic
        #lif num <= 22:
        elif ltype == "orthorhombic":
            vec = random_vector()
            if PA == 3:
                ratio = abs(vec[0]/vec[1]) #ratio a/b
                abc[1] = sqrt(volume/(thickness1*ratio))
                abc[0] = abc[1]* ratio
            elif PA == 2:
                ratio = abs(vec[0]/vec[2]) #ratio a/b
                abc[2] = sqrt(volume/(thickness1*ratio))
                abc[0] = abc[2]* ratio
            elif PA == 1:
                ratio = abs(vec[1]/vec[2]) #ratio a/b
                abc[2] = sqrt(volume/(thickness1*ratio))
                abc[1] = abc[2]* ratio

        #Tetragonal
        #elif num <= 41:
        elif ltype == "tetragonal":
            if PA == 3:
                abc[0] = abc[1] = sqrt(volume/thickness1)
            elif PA == 2:
                abc[0] = abc[1]
                abc[2] = volume/(abc[PA-1]**2)
            elif PA == 1:
                abc[1] = abc[0]
                abc[2] = volume/(abc[PA-1]**2)

        #Trigonal/Rhombohedral/Hexagonal
        #elif num <= 75:
        elif ltype == "hexagonal":
            gamma = pi/3*2
            x = sqrt(3.)/2.
            if PA == 3:
                abc[0] = abc[1] = sqrt((volume/x)/abc[PA-1])
            elif PA == 2:
                abc[0] = abc[1]
                abc[2] = (volume/x)(thickness1**2)
            elif PA == 1:
                abc[1] = abc[0]
                abc[2] = (volume/x)/(thickness1**2)

        para = np.array([abc[0], abc[1], abc[2], alpha, beta, gamma])

        a, b, c = abc[0], abc[1], abc[2]
        maxvec = (a*b*c)/(minvec**2)

        #Define limits on cell dimensions
        if 'min_l' not in kwargs:
            min_l = minvec
        else:
            min_l = kwargs['min_l']
        if 'mid_l' not in kwargs:
            mid_l = min_l
        else:
            mid_l = kwargs['mid_l']
        if 'max_l' not in kwargs:
            max_l = mid_l
        else:
            max_l = kwargs['max_l']
        l_min = min(a, b, c)
        l_max = max(a, b, c)
        for x in (a, b, c):
            if x <= l_max and x >= l_min:
                l_mid = x
        if not (l_min >= min_l and l_mid >= mid_l and l_max >= max_l):
            continue

        if minvec < maxvec:
            smallvec = min(a*cos(max(beta, gamma)), b*cos(max(alpha, gamma)), c*cos(max(alpha, beta)))
            if(a>minvec and b>minvec and c>minvec
            and a<maxvec and b<maxvec and c<maxvec
            and smallvec < minvec
            and alpha>minangle and beta>minangle and gamma>minangle
            and alpha<maxangle and beta<maxangle and gamma<maxangle
            and a/b<max_ratio and a/c<max_ratio and b/c<max_ratio
            and b/a<max_ratio and c/a<max_ratio and c/b<max_ratio):
                return para

    #If maxattempts tries have been made without success
    print("Error: Could not generate lattice after "+str(n+1)+" attempts")
    return

def generate_lattice_0D(ltype, volume, area=None, minvec=tol_m, max_ratio=20.0, maxattempts = 100, **kwargs):
    """
    Generates a lattice (3x3 matrix) according to the spacegroup symmetry and
    number of atoms. If the spacegroup has centering, we will transform to
    conventional cell setting. If the generated lattice does not meet the
    minimum angle and vector requirements, we try to generate a new one, up to
    maxattempts times.
    Note: The monoclinic Rod groups have different unique axes. Groups 3-7
        have unique axis a, while 8-12 have unique axis c. We use periodic
        axis c for all Rod groups.

    Args:
        num: number of the Rod group
        volume: volume of the lattice
        area: cross-sectional area of the unit cell in Angstroms squared. If
            set to None, a value is chosen automatically
        minvec: minimum allowed lattice vector length (among a, b, and c)
        max_ratio: largest allowed ratio of two lattice vector lengths
        maxattempts: the maximum number of attempts for generating a lattice
        kwargs: a dictionary of optional values. Only used for cylindrical
            lattices, which pass the value to generate_lattice. Possible values include:
            'unique_axis': the axis ('a', 'b', or 'c') which is not symmetrically
                equivalent to the other two
            'min_l': the smallest allowed cell vector. The smallest vector must be larger
                than this.
            'mid_l': the second smallest allowed cell vector. The second smallest vector
                must be larger than this.
            'max_l': the third smallest allowed cell vector. The largest cell vector must
                be larger than this.

    Returns:
        a 3x3 matrix representing the lattice vectors of the unit cell. If
        generation fails, outputs a warning message and returns empty
    """
    if ltype == "spherical":
        #Use a cubic lattice with altered volume
        a = b = c = np.cbrt((3 * volume)/(4 * pi))
        alpha = beta = gamma = 0.5 * pi
        if a < minvec:
            print("Error: Could not generate spherical lattice; volume too small compared to minvec")
            return
        return np.array([a, b, c, alpha, beta, gamma])
    if ltype == "cylindrical":
        #Use a tetragonal lattice with altered volume
        return generate_lattice("tetragonal", volume*4/pi, minvec=minvec, max_ratio=max_ratio, maxattempts=maxattempts, **kwargs)

def choose_wyckoff(group, number):
    """
    Choose a Wyckoff position to fill based on the current number of atoms
    needed to be placed within a unit cell
    Rules:
        1) The new position's multiplicity is equal/less than (number).
        2) We prefer positions with large multiplicity.

    Args:
        group: a pyxtal.symmetry.Group object
        number: the number of atoms still needed in the unit cell

    Returns:
        a single index for the Wyckoff position. If no position is found,
        returns False
    """
    wyckoffs_organized = group.wyckoffs_organized
    
    if rand_u(0,1)>0.5: #choose from high to low
        for wyckoff in wyckoffs_organized:
            if len(wyckoff[0]) <= number:
                return choose(wyckoff)
        return False
    else:
        good_wyckoff = []
        for wyckoff in wyckoffs_organized:
            if len(wyckoff[0]) <= number:
                for w in wyckoff:
                    good_wyckoff.append(w)
        if len(good_wyckoff) > 0:
            return choose(good_wyckoff)
        else:
            return False

class Wyckoff_site():
    """
    Class for storing atomic Wyckoff positions with a single coordinate.
    
    Args:
        wp: a Wyckoff_position object
        coordinate: a fractional 3-vector for the generating atom's coordinate
        specie: an Element, element name or symbol, or atomic number of the atom
    """
    def __init__(self, wp, coordinate, specie):
        if type(wp) == Wyckoff_position:
            self.wp = wp
        else:
            print("Error: wp must be a Wyckoff_position object.")
            return
        self.position = np.array(coordinate)
        self.specie = Element(specie).short_name

    def __str__(self):
        return self.specie+": "+str(self.position)+" "+str(self.wp.multiplicity)+self.wp.letter+", site symmetry "+ss_string_from_ops(self.wp.symmetry_m[0], self.wp.number, dim=self.wp.dim)

    def __repr__(self):
        return str(self)

def verify_distances(coordinates, species, lattice, factor=1.0, PBC=[1,1,1]):
    """
    Checks the inter-atomic distance between all pairs of atoms in a crystal.

    Args:
        coordinates: a 1x3 list of fractional coordinates
        species: a list of atomic symbols for each coordinate
        lattice: a 3x3 matrix representing the lattice vectors of the unit cell
        factor: a tolerance factor for checking distances. A larger value means
            atoms must be farther apart
        PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
            Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis
    
    Returns:
        True if no atoms are too close together, False if any pair is too close
    """
    for i, c1 in enumerate(coordinates):
        specie1 = species[i]
        for j, c2 in enumerate(coordinates):
            if j > i:
                specie2 = species[j]
                diff = np.array(c2) - np.array(c1)
                d_min = distance(diff, lattice, PBC=PBC)
                tol = factor*0.5*(Element(specie1).covalent_radius + Element(specie2).covalent_radius)
                if d_min < tol:
                    return False
    return True

class Lattice():
    """
    Class for storing and generating crystal lattices. Allows for specification
    of constraint values. Lattice types include triclinic, monoclinic, orthorhombic,
    tetragonal, trigonal, hexagonal, cubic, spherical, and cylindrical. The last
    two are used for generating point group structures, and do not actually represent
    a parallelepiped lattice.

    Args:
        ltype: a string representing the type of lattice (from the above list)
        volume: the volume, in Angstroms cubed, of the lattice
        PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
            Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis
        kwargs: various values which may be defined. If none are defined, random ones
            will be generated. Values will be passed to generate_lattice. Options include:
            area: The cross-sectional area (in Angstroms squared). Only used to generate 1D
                crystals
            thickness: The unit cell's non-periodic thickness (in Angstroms). Only used to
                generate 2D crystals
            unique_axis: The unique axis for certain symmetry (and especially layer) groups.
                Because the symmetry operations are not also transformed, you should use the
                default values for random crystal generation
            random: If False, keeps the stored values for the lattice geometry even upon applying
                reset_matrix. To alter the matrix, use set_matrix() or set_para
            'unique_axis': the axis ('a', 'b', or 'c') which is not symmetrically
                equivalent to the other two
            'min_l': the smallest allowed cell vector. The smallest vector must be larger
                than this.
            'mid_l': the second smallest allowed cell vector. The second smallest vector
                must be larger than this.
            'max_l': the third smallest allowed cell vector. The largest cell vector must
                be larger than this.
    """
    def __init__(self, ltype, volume, PBC=[1,1,1], **kwargs):
        #Set required parameters
        if ltype in ["triclinic", "monoclinic", "orthorhombic", "tetragonal",
                "trigonal", "hexagonal", "cubic", "spherical", "cylindrical"]:
            self.ltype = ltype
        elif ltype == None:
            self.ltype = "triclinic"
        else:
            print("Error: Invalid lattice type.")
            return
        self.volume = float(volume)
        self.PBC = PBC
        self.dim = sum(PBC)
        self.kwargs = {}
        self.random = True
        #Set optional values
        for key, value in kwargs.items():
            if key in ["area", "thickness", "unique_axis", "random", "min_l", "mid_l", "max_l"]:
                setattr(self, key, value)
                self.kwargs[key] = value
        self.reset_matrix()
        
    def generate_para(self):
        if self.dim == 3:
            return generate_lattice(self.ltype, self.volume, **self.kwargs)
        elif self.dim == 2:
            return generate_lattice_2D(self.ltype, self.volume, **self.kwargs)
        elif self.dim == 1:
            return generate_lattice_1D(self.ltype, self.volume, **self.kwargs)
        elif self.dim == 0:
            return generate_lattice_0D(self.ltype, self.volume, **self.kwargs)

    def generate_matrix(self):
        """
        Generates a 3x3 matrix for the lattice based on the lattice type and volume
        """
        #Try multiple times in case of failure
        for i in range(10):
            para = self.generate_para()
            if para is not None:
                return para2matrix(para)
        print("Error: Could not generate lattice matrix.")
        return

    def get_matrix(self):
        """
        Returns a 3x3 numpy array representing the lattice vectors.
        """
        try:
            return self.matrix
        except:
            print("Error: Lattice matrix undefined.")
            return

    def get_para(self):
        """
        Returns a tuple of lattice parameters.
        """
        return (self.a, self.b, self.c, self.alpha, self.beta, self.gamma)

    def set_matrix(self, matrix=None):
        if matrix != None:
            m = np.array(matrix)
            if np.shape(m) == (3,3):
                self.matrix = m
            else:
                print("Error: matrix must be a 3x3 numpy array or list")
        elif matrix == None:
            self.reset_matrix()
        para = matrix2para(self.matrix)
        self.a, self.b, self.c, self.alpha, self.beta, self.gamma = para

    def set_para(self, para=None, radians=False):
        if para is not None:
            if radians is False:
                para[3] *= rad
                para[4] *= rad
                para[5] *= rad
            self.set_matrix(para2matrix(para))
        else:
            self.set_matrix()

    def reset_matrix(self):
        if self.random is True:
            self.matrix = self.generate_matrix()
            [a, b, c, alpha, beta, gamma] = matrix2para(self.matrix)
            self.a = a
            self.b = b
            self.c = c
            self.alpha = alpha
            self.beta = beta
            self.gamma = gamma

    def generate_point(self):
        point = np.random.random(3)
        if self.ltype == "spherical":
            #Choose a point within an octant of the unit sphere
            while dsquared(point) > 1:
                point = np.random.random(3)
            #Randomly flip some coordinates
            for index, x in enumerate(point):
                #Scale the point by the max radius
                if rand_u(0,1) < 0.5:
                    point[index] *= -1

        elif self.ltype == "cylindrical":
            #Choose a point within an octant of the unit sphere
            while dsquared([point[0], point[1], 0]) > 1:
                point = np.random.random(3)
            #Randomly flip some coordinates
            for index, x in enumerate(point[:-1]):
                #Scale the point by the max radius
                if rand_u(0,1) < 0.5:
                    point[index] *= -1
        else:
            for i, a in enumerate(self.PBC):
                if not a:
                    if self.ltype == "hexagonal":
                        point[i] *= 1./sqrt(3.)
                    else:
                        point[i] -= 0.5
        return point

    def from_para(a, b, c, alpha, beta, gamma, ltype="triclinic", radians=False, PBC=[1,1,1], **kwargs):
        """
        Creates a Lattice object from 6 lattice parameters. Additional keyword arguments
        are available. Unless specified by the keyword random=True, does not create a
        new matrix upon calling reset_matrix. This allows for generation of random
        crystals with a specific choice of unit cell.

        Args:
            a, b, c: The length (in Angstroms) of the unit cell vectors
            alpha: the angle (in degrees) between the b and c vectors
            beta: the angle (in degrees) between the a and c vectors
            gamma: the angle (in degrees) between the a and b vectors
            ltype: the lattice type ("cubic, tetragonal, etc."). Also available are "spherical",
                which confines generated points to lie within a sphere, and "cylindrical", which
                confines generated points to lie within a cylinder (oriented about the z axis)
            radians: whether or not to use radians (instead of degrees) for the lattice angles
            PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
                Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis
            kwargs: various values which may be defined. If none are defined, random ones
                will be generated. Values will be passed to generate_lattice. Options include:
                area: The cross-sectional area (in Angstroms squared). Only used to generate 1D
                    crystals
                thickness: The unit cell's non-periodic thickness (in Angstroms). Only used to
                    generate 2D crystals
                unique_axis: The unique axis for certain symmetry (and especially layer) groups.
                    Because the symmetry operations are not also transformed, you should use the
                    default values for random crystal generation
                random: If False, keeps the stored values for the lattice geometry even upon applying
                    reset_matrix. To alter the matrix, use set_matrix() or set_para
                'unique_axis': the axis ('a', 'b', or 'c') which is not symmetrically
                    equivalent to the other two
                'min_l': the smallest allowed cell vector. The smallest vector must be larger
                    than this.
                'mid_l': the second smallest allowed cell vector. The second smallest vector
                    must be larger than this.
                'max_l': the third smallest allowed cell vector. The largest cell vector must
                    be larger than this.

        Returns:
            a Lattice object with the specified parameters
        """
        try:
            cell_matrix = para2matrix((a,b,c,alpha,beta,gamma), radians=radians)
        except:
            print("Error: invalid cell parameters for lattice.")
            return
        volume = np.linalg.det(cell_matrix)
        #Initialize a Lattice instance
        l = Lattice(ltype, volume, PBC=PBC, **kwargs)
        l.a = a
        l.b = b
        l.c = c
        l.alpha = alpha*rad
        l.beta = beta*rad
        l.gamma = gamma*rad
        l.matrix = cell_matrix
        l.ltype = ltype
        l.volume = volume
        l.random = False
        return l

    def from_matrix(matrix, ltype="triclinic", PBC=[1,1,1], **kwargs):
        """
        Creates a Lattice object from a 3x3 cell matrix. Additional keyword arguments
        are available. Unless specified by the keyword random=True, does not create a
        new matrix upon calling reset_matrix. This allows for generation of random
        crystals with a specific choice of unit cell.

        Args:
            matrix: a 3x3 real matrix (numpy array or nested list) describing the cell vectors
            ltype: the lattice type ("cubic, tetragonal, etc."). Also available are "spherical",
                which confines generated points to lie within a sphere, and "cylindrical", which
                confines generated points to lie within a cylinder (oriented about the z axis)
            PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
                Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis
            kwargs: various values which may be defined. If none are defined, random ones
                will be generated. Values will be passed to generate_lattice. Options include:
                area: The cross-sectional area (in Angstroms squared). Only used to generate 1D
                    crystals
                thickness: The unit cell's non-periodic thickness (in Angstroms). Only used to
                    generate 2D crystals
                unique_axis: The unique axis for certain symmetry (and especially layer) groups.
                    Because the symmetry operations are not also transformed, you should use the
                    default values for random crystal generation
                random: If False, keeps the stored values for the lattice geometry even upon applying
                    reset_matrix. To alter the matrix, use set_matrix() or set_para
                'unique_axis': the axis ('a', 'b', or 'c') which is not symmetrically
                    equivalent to the other two
                'min_l': the smallest allowed cell vector. The smallest vector must be larger
                    than this.
                'mid_l': the second smallest allowed cell vector. The second smallest vector
                    must be larger than this.
                'max_l': the third smallest allowed cell vector. The largest cell vector must
                    be larger than this.

        Returns:
            a Lattice object with the specified parameters
        """
        pass
        m = np.array(matrix)
        if np.shape(m) != (3,3):
            print("Error: Lattice matrix must be 3x3")
            return
        [a, b, c, alpha, beta, gamma] = matrix2para(m)
        volume = np.linalg.det(m)
        #Initialize a Lattice instance
        l = Lattice(ltype, volume, PBC=PBC, **kwargs)
        l.a = a
        l.b = b
        l.c = c
        l.alpha = alpha
        l.beta = beta
        l.gamma = gamma
        l.matrix = m
        l.ltype = ltype
        l.volume = volume
        l.random = False
        return l

    def __str__(self):
        s = str(self.ltype)+" lattice:"
        s += "\na: "+str(self.a)
        s += "\nb: "+str(self.b)
        s += "\nc: "+str(self.c)
        s += "\nalpha: "+str(self.alpha*deg)
        s += "\nbeta: "+str(self.beta*deg)
        s += "\ngamma: "+str(self.gamma*deg)
        return s

    def __repr__(self):
        return str(self)

class random_crystal():
    """
    Class for storing and generating atomic crystals based on symmetry
    constraints. Given a spacegroup, list of atomic symbols, the stoichiometry,
    and a volume factor, generates a random crystal consistent with the
    spacegroup's symmetry. This crystal is stored as a pymatgen struct via
    self.struct
    
    Args:
        group: the international spacegroup number, or a Group object
        species: a list of atomic symbols for each ion type
        numIons: a list of the number of each type of atom within the
            primitive cell (NOT the conventional cell)
        tm: the Tol_matrix object used to generate the crystal
        factor: a volume factor used to generate a larger or smaller
            unit cell. Increasing this gives extra space between atoms
        lattice: an optional Lattice object to use for the unit cell
    """
    def init_common(self, species, numIons, factor, group, lattice, tm):
        """
        Common init functionality for 0D-3D cases of random_crystal.
        """
        if type(group) == Group:
            self.group = group
            """A pyxtal.symmetry.Group object storing information about the space/layer
            /Rod/point group, and its Wyckoff positions."""
        else:
            self.group = Group(group, dim=self.dim)
        self.number = self.group.number
        """The international group number of the crystal:
        1-230 for 3D space groups
        1-80 for 2D layer groups
        1-75 for 1D Rod groups
        1-32 for crystallographic point groups
        None otherwise
        """
        self.numattempts = 0
        """The number of attempts needed to generate the crystal. Has a maximum
        value of max1*max2*max3."""
        numIons = np.array(numIons) #must convert it to np.array
        self.factor = factor
        """The supplied volume factor for the unit cell."""
        self.numIons0 = numIons
        """The number of each type of atom in the PRIMITIVE cell."""
        self.numIons = self.numIons0 * cellsize(self.group)
        """The number of each type of atom in the CONVENTIONAL cell."""
        self.species = species
        """A list of atomic symbols for the types of atoms in the crystal."""
        self.Msgs()
        """A list of warning messages to use during generation."""
        if lattice is not None:
            #Use the provided lattice
            self.lattice = lattice
            self.volume = lattice.volume
        elif lattice == None:
            #Determine the unique axis
            if self.dim == 2:
                if self.number in range(3, 8):
                    unique_axis = "c"
                else:
                    unique_axis = "a"
            elif self.dim == 1:
                if self.number in range(3, 8):
                    unique_axis = "a"
                else:
                    unique_axis = "c"
            else:
                unique_axis = "c"
            #Generate a Lattice instance
            self.volume = estimate_volume(self.numIons, self.species, self.factor)
            """The volume of the generated unit cell."""
            if self.dim == 3 or self.dim == 0:
                self.lattice = Lattice(self.group.lattice_type, self.volume, PBC=self.PBC, unique_axis=unique_axis)
            elif self.dim == 2:
                self.lattice = Lattice(self.group.lattice_type, self.volume, PBC=self.PBC, unique_axis=unique_axis, thickness=self.thickness)
            elif self.dim == 1:
                self.lattice = Lattice(self.group.lattice_type, self.volume, PBC=self.PBC, unique_axis=unique_axis, area=self.area)
        #Set the tolerance matrix
        if type(tm) == Tol_matrix:
            self.tol_matrix = tm
            """The Tol_matrix object used for checking inter-atomic distances within the structure."""
        else:
            try:
                self.tol_matrix = Tol_matrix(prototype=tm)
            except:
                print("Error: tm must either be a Tol_matrix object or a prototype string for initializing one.")
                self.valid = False
                self.struct = None
                return
        #Generate the crystal
        self.generate_crystal()

    def __init__(self, group, species, numIons, factor, lattice=None, tm=Tol_matrix(prototype="atomic")):
        self.dim = 3
        """The number of periodic dimensions of the crystal"""
        if type(group) != Group:
            group = Group(group, self.dim)
        self.sg = group.number
        """The international spacegroup number of the crystal."""
        self.PBC = [1,1,1]
        """The periodic boundary axes of the crystal"""
        self.init_common(species, numIons, factor, group, lattice, tm)

    def Msgs(self):
        """
        Define a set of error and warning message if generation fails.

        Returns:
            nothing
        """
        self.Msg1 = 'Error: the number is incompatible with the wyckoff sites choice'
        self.Msg2 = 'Error: failed in the cycle of generating structures'
        self.Msg3 = 'Warning: failed in the cycle of adding species'
        self.Msg4 = 'Warning: failed in the cycle of choosing wyckoff sites'
        self.Msg5 = 'Finishing: added the specie'
        self.Msg6 = 'Finishing: added the whole structure'

    def check_compatible(self):
        """
        Checks if the number of atoms is compatible with the Wyckoff
        positions. Considers the number of degrees of freedom for each Wyckoff
        position, and makes sure at least one valid combination of WP's exists.
        """
        N_site = [len(x[0]) for x in self.group.wyckoffs_organized]
        has_freedom = False
        #remove WP's with no freedom once they are filled
        removed_wyckoffs = []
        for numIon in self.numIons:
            #Check that the number of ions is a multiple of the smallest Wyckoff position
            if numIon % N_site[-1] > 0:
                return False
            else:
                #Check if smallest WP has at least one degree of freedom
                op = self.group.wyckoffs_organized[-1][-1][0]
                if op.rotation_matrix.all() != 0.0:
                    has_freedom = True
                else:
                    #Subtract from the number of ions beginning with the smallest Wyckoff positions
                    remaining = numIon
                    for x in self.group.wyckoffs_organized:
                        for wp in x:
                            removed = False
                            while remaining >= len(wp) and wp not in removed_wyckoffs:
                                #Check if WP has at least one degree of freedom
                                op = wp[0]
                                remaining -= len(wp)
                                if np.allclose(op.rotation_matrix, np.zeros([3,3])):
                                    removed_wyckoffs.append(wp)
                                    removed = True
                                else:
                                    has_freedom = True
                    if remaining != 0:
                        return False
        if has_freedom:
            return True
        else:
            #Wyckoff Positions have no degrees of freedom
            return 0

    def to_file(self, fmt="cif", filename=None):
        """
        Creates a file with the given filename and file type to store the structure.
        By default, creates cif files for crystals and xyz files for clusters.
        By default, the filename is based on the stoichiometry.

        Args:
            fmt: the file type ('cif', 'xyz', etc.)
            filename: the file path

        Returns:
            Nothing. Creates a file at the specified path
        """
        if filename == None:
            given = False
        else:
            given = True
        if self.valid:
            if self.dim == 0:
                if filename == None:
                    filename = str(self.molecule.formula).replace(" ","") + "." + fmt
            if self.dim != 0:
                if filename == None:
                    filename = str(self.struct.formula).replace(" ","") + "." + fmt
            #Check if filename already exists
            #If it does, add a new number to end of filename
            if exists(filename):
                if given is False:
                    filename = filename[:(-len(fmt)-1)]
                i = 1
                while True:
                    outdir = filename + "_" + str(i)
                    if given is False:
                        outdir += "." + fmt
                    if not exists(outdir):
                        break
                    i += 1
                    if i > 10000:
                        return "Could not create file: too many files already created."
            else:
                outdir = filename
            if self.dim == 0 and fmt == "xyz":
                self.molecule.to(fmt=fmt, filename=outdir)
            else:
                self.struct.to(fmt=fmt, filename=outdir)
            return "Output file to " + outdir
        elif self.valid is False:
            print("Cannot create file: structure did not generate.")

    def print_all(self):
        """
        Prints useful information about the generated crystal.
        """
        print("--Random Crystal--")
        print("Dimension: "+str(self.dim))
        print("Group: "+self.group.symbol)
        print("Volume factor: "+str(self.factor))
        if self.valid is True:
            print("Wyckoff sites:")
            for x in self.wyckoff_sites:
                print("  "+str(x))
            print("Pymatgen Structure:")
            print(self.struct)
        elif self.valid is False:
            print("Structure not generated.")

    def generate_crystal(self, max1=max1, max2=max2, max3=max3):
        """
        The main code to generate a random atomic crystal. If successful,
        stores a pymatgen.core.structure object in self.struct and sets
        self.valid to True. If unsuccessful, sets self.valid to False and
        outputs an error message.

        Args:
            max1: the number of attempts for generating a lattice
            max2: the number of attempts for a given lattice
            max3: the number of attempts for a given Wyckoff position
        """
        #Check the minimum number of degrees of freedom within the Wyckoff positions
        self.numattempts = 1
        degrees = self.check_compatible()
        if degrees is False:
            print(self.Msg1)
            self.struct = None
            self.valid = False
            return
        else:
            if degrees is 0:
                max1 = 5
                max2 = 5
                max3 = 5
            #Calculate a minimum vector length for generating a lattice
            minvector = max(max(2.0*Element(specie).covalent_radius for specie in self.species), tol_m)
            for cycle1 in range(max1):
                #1, Generate a lattice
                self.lattice.reset_matrix()           
                cell_matrix = self.lattice.get_matrix()
                #Check that the correct volume was generated
                if self.lattice.random is True:
                    if self.dim != 0 and abs(self.volume - np.linalg.det(cell_matrix)) > 1.0: 
                        print('Error, volume is not equal to the estimated value: ', self.volume, ' -> ', np.linalg.det(cell_matrix))
                        print('cell_para:  ', matrix2para(cell_matrix))
                        sys.exit(0)

                coordinates_total = [] #to store the added coordinates
                sites_total = []      #to store the corresponding specie
                wyckoff_sites_total = []
                good_structure = False

                for cycle2 in range(max2):
                    coordinates_tmp = deepcopy(coordinates_total)
                    sites_tmp = deepcopy(sites_total)
                    wyckoff_sites_tmp = deepcopy(wyckoff_sites_total)
                    
                    #Add specie by specie
                    for numIon, specie in zip(self.numIons, self.species):
                        numIon_added = 0
                        tol = max(0.5*Element(specie).covalent_radius, tol_m)

                        #Now we start to add the specie to the wyckoff position
                        cycle3 = 0
                        while cycle3 < max3:
                            #Choose a random Wyckoff position for given multiplicity: 2a, 2b, 2c
                            ops = choose_wyckoff(self.group, numIon-numIon_added) 
                            if ops is not False:
                            #Generate a list of coords from ops
                                point = self.lattice.generate_point()
                                coords = np.array([op.operate(point) for op in ops])
                                #Merge coordinates if the atoms are close
                                coords_toadd, good_merge, point = merge_coordinate(coords, cell_matrix, self.group, tol)
                                if good_merge is not False:
                                    coords_toadd = filtered_coords(coords_toadd, PBC=self.PBC)
                                    if check_distance(coordinates_tmp, coords_toadd, sites_tmp, [specie]*len(coords_toadd), cell_matrix, tm=self.tol_matrix, PBC=self.PBC):
                                        if coordinates_tmp == []:
                                            coordinates_tmp = coords_toadd
                                        else:
                                            coordinates_tmp = np.vstack([coordinates_tmp, coords_toadd])
                                        sites_tmp += [specie]*len(coords_toadd)
                                        wyckoff_sites_tmp.append(Wyckoff_site(ops, point, specie))
                                        numIon_added += len(coords_toadd)
                                    else:
                                        cycle3 += 1
                                        self.numattempts += 1
                                    if numIon_added == numIon:
                                        coordinates_total = deepcopy(coordinates_tmp)
                                        sites_total = deepcopy(sites_tmp)
                                        wyckoff_sites_total = deepcopy(wyckoff_sites_tmp)
                                        break
                                else:
                                    cycle3 += 1
                                    self.numattempts += 1
                            else:
                                cycle3 += 1
                                self.numattempts ++ 1

                        if numIon_added != numIon:
                            break  #need to repeat from the 1st species

                    if numIon_added == numIon:
                        good_structure = True
                        break
                    else: #reset the coordinates and sites
                        coordinates_total = []
                        sites_total = []

                if good_structure:
                    final_coor = []
                    final_site = []
                    final_number = []
                    final_lattice = cell_matrix
                    for coor, ele in zip(coordinates_total, sites_total):
                        final_coor.append(coor)
                        final_site.append(ele)
                        final_number.append(Element(ele).z)
                    final_coor = np.array(final_coor)

                    if self.dim != 0:
                        final_lattice, final_coor = Add_vacuum(final_lattice, final_coor, PBC=self.PBC)
                        self.lattice_matrix = final_lattice   
                        """A 3x3 matrix representing the lattice of the unit
                        cell."""                 
                        self.coordinates = np.array(final_coor)
                        """The fractional coordinates for each atom in the
                        final structure"""
                        self.sites = final_site
                        """A list of atomic symbols corresponding to the type
                        of atom for each site in self.coordinates"""
                        self.struct = Structure(final_lattice, final_site, np.array(final_coor))
                        """A pymatgen.core.structure.Structure object for the
                        final generated crystal."""
                        self.spg_struct = (final_lattice, np.array(final_coor), final_number)
                        """A list of information describing the generated
                        crystal, which may be used by spglib for symmetry
                        analysis."""
                        self.wyckoff_sites = wyckoff_sites_total
                        """A list of Wyckoff_site objects describing the Wyckoff positions in
                        the structure."""
                        self.valid = True
                        return
                    elif self.dim == 0:
                        if verify_distances(final_coor, final_site, cell_matrix, PBC=self.PBC):
                            self.lattice_matrix = final_lattice   
                            """A 3x3 matrix representing the lattice of the unit
                            cell."""        
                            self.coordinates = final_coor
                            """The absolute coordinates for each atom in the
                            final structure"""
                            self.sites = final_site
                            """A list of atomic symbols corresponding to the type
                            of atom for each site in self.coordinates"""
                            self.species = final_site
                            """A list of atomic symbols corresponding to the type
                            of atom for each site in self.coordinates"""
                            absolute_coords = np.dot(self.coordinates, cell_matrix)
                            self.molecule = Molecule(self.species, absolute_coords)
                            """A pymatgen.core.structure.Molecule object for the
                            final generated cluster."""
                            #Calculate binding box
                            maxx = max(absolute_coords[:,0])
                            minx = min(absolute_coords[:,0])
                            maxy = max(absolute_coords[:,1])
                            miny = min(absolute_coords[:,1])
                            maxz = max(absolute_coords[:,2])
                            minz = min(absolute_coords[:,2])
                            self.struct = self.molecule.get_boxed_structure(maxx-minx+10, maxy-miny+10, maxz-minz+10)
                            """A pymatgen.core.structure.Structure object for the
                            final generated object."""
                            self.wyckoff_sites = wyckoff_sites_total
                            """A list of Wyckoff_site objects describing the Wyckoff positions in
                            the structure."""
                            self.valid = True
                            """Whether or not a valid crystal was generated."""
                            return
        if degrees == 0: print("Wyckoff positions have no degrees of freedom.")
        self.struct = self.Msg2
        self.valid = False
        return self.Msg2

class random_crystal_2D(random_crystal):
    """
    A 2d counterpart to random_crystal. Generates a random atomic crystal based
    on a 2d layer group instead of a 3d spacegroup. Note that each layer group
    is equal to a corresponding 3d spacegroup, but without periodicity in one
    direction. The generated pymatgen structure can be accessed via self.struct

    Args:
        group: the layer group number between 1 and 80. NOT equal to the
            international space group number, which is between 1 and 230
            OR, a pyxtal.symmetry.Group object
        species: a list of atomic symbols for each ion type
        numIons: a list of the number of each type of atom within the
            primitive cell (NOT the conventional cell)
        thickness: the thickness, in Angstroms, of the unit cell in the 3rd
            dimension (the direction which is not repeated periodically)
        factor: a volume factor used to generate a larger or smaller
            unit cell. Increasing this gives extra space between atoms
        lattice: an optional Lattice object to use for the unit cell
        tm: the Tol_matrix object used to generate the crystal
    """
    def __init__(self, group, species, numIons, factor, thickness=None, lattice=None, tm=Tol_matrix(prototype="atomic")):
        self.dim = 2
        """The number of periodic dimensions of the crystal"""
        self.PBC = [1,1,0]
        """The periodic boundary axes of the crystal"""
        if type(group) != Group:
            group = Group(group, self.dim)
        number = group.number
        """The layer group number of the crystal."""
        self.lgp = Layergroup(number)
        """A Layergroup object for the crystal's layer group."""
        self.sg = self.lgp.sgnumber
        """The number (between 1 and 230) for the international spacegroup."""
        self.thickness = thickness
        """the thickness, in Angstroms, of the unit cell in the 3rd
        dimension."""
        self.init_common(species, numIons, factor, number, lattice, tm)

class random_crystal_1D(random_crystal):
    """
    A 1d counterpart to random_crystal. Generates a random atomic crystal based
    on a 1d Rod group instead of a 3d spacegroup. The generated pymatgen
    structure can be accessed via self.struct

    Args:
        group: the Rod group number between 1 and 75. NOT equal to the
            international space group number, which is between 1 and 230
            OR, a pyxtal.symmetry.Group object
        species: a list of atomic symbols for each ion type
        numIons: a list of the number of each type of atom within the
            primitive cell (NOT the conventional cell)
        area: the effective cross-sectional area, in Angstroms squared, of the
            unit cell
        factor: a volume factor used to generate a larger or smaller
            unit cell. Increasing this gives extra space between atoms
        lattice: an optional Lattice object to use for the unit cell
        tm: the Tol_matrix object used to generate the crystal
    """
    def __init__(self, group, species, numIons, factor, area=None, lattice=None, tm=Tol_matrix(prototype="atomic")):
        self.dim = 1
        """The number of periodic dimensions of the crystal"""
        self.PBC = [0,0,1]
        """The periodic axis of the crystal."""
        self.sg = None
        """The international space group number (there is not a 1-1 correspondence
        with Rod groups)."""
        self.area = area
        """the effective cross-sectional area, in Angstroms squared, of the
        unit cell."""
        self.init_common(species, numIons, factor, group, lattice, tm)

class random_cluster(random_crystal):
    """
    A 0d counterpart to random_crystal. Generates a random atomic cluster based
    on a 0d Point group instead of a 3d spacegroup. The generated pymatgen
    structure can be accessed via self.struct

    Args:
        group: the Schoenflies symbol for the point group (ex: "Oh", "C5v", "D3")
            OR the number between 1-32 for a crystallographic point group,
            OR, a pyxtal.symmetry.Group object
            See:
            https://en.wikipedia.org/wiki/Schoenflies_notation#Point_groups
            for more information
        species: a list of atomic symbols for each ion type
        numIons: a list of the number of each type of atom within the
            primitive cell (NOT the conventional cell)
        factor: a volume factor used to generate a larger or smaller
            unit cell. Increasing this gives extra space between atoms
        lattice: an optional Lattice object to use for the unit cell
        tm: the Tol_matrix object used to generate the crystal
    """
    def __init__(self, group, species, numIons, factor, lattice=None, tm=Tol_matrix(prototype="atomic")):
        self.dim = 0
        """The number of periodic dimensions of the crystal"""
        self.PBC = [0,0,0]
        """The periodic axis of the crystal."""
        self.sg = None
        """The international space group number (there is not a 1-1 correspondence
        with Point groups)."""
        self.init_common(species, numIons, factor, group, lattice, tm)


if __name__ == "__main__":
    #-------------------------------- Options -------------------------
    import os
    parser = OptionParser()
    parser.add_option("-s", "--spacegroup", dest="sg", metavar='sg', default=36, type=int,
            help="desired space group number (1-230) or layer group number (1-80), e.g., 36")
    parser.add_option("-e", "--element", dest="element", default='Li', 
            help="desired elements: e.g., Li", metavar="element")
    parser.add_option("-n", "--numIons", dest="numIons", default=16, 
            help="desired numbers of atoms: 16", metavar="numIons")
    parser.add_option("-f", "--factor", dest="factor", default=1.0, type=float, 
            help="volume factor: default 1.0", metavar="factor")
    parser.add_option("-v", "--verbosity", dest="verbosity", default=0, type=int, 
            help="verbosity: default 0; higher values print more information", metavar="verbosity")
    parser.add_option("-a", "--attempts", dest="attempts", default=1, type=int, 
            help="number of crystals to generate: default 1", metavar="attempts")
    parser.add_option("-o", "--outdir", dest="outdir", default="out", type=str, 
            help="Directory for storing output cif files: default 'out'", metavar="outdir")
    parser.add_option("-d", "--dimension", dest="dimension", metavar='dimension', default=3, type=int,
            help="desired dimension: (3, 2, or 1 for 3d, 2d, or 1D respectively): default 3")
    parser.add_option("-t", "--thickness", dest="thickness", metavar='thickness', default=None, type=float,
            help="Thickness, in Angstroms, of a 2D crystal, or area of a 1D crystal, None generates a value automatically: default None")

    (options, args) = parser.parse_args()
    sg = options.sg
    dimension = options.dimension
    if dimension == 3:
        if sg < 1 or sg > 230:
            print("Invalid space group number. Must be between 1 and 230.")
            sys.exit(0)
    elif dimension == 2:
        if sg < 1 or sg > 80:
            print("Invalid layer group number. Must be between 1 and 80.")
            sys.exit(0)
    elif dimension == 1:
        if sg < 1 or sg > 75:
            print("Invalid Rod group number. Must be between 1 and 75.")
            sys.exit(0)
    else:
        print("Invalid dimension. Use dimension 0, 1, 2, or 3.")
        sys.exit(0)

    element = options.element
    number = options.numIons
    numIons = []
    if element.find(',') > 0:
        system = element.split(',')
        for x in number.split(','):
            numIons.append(int(x))
    else:
        system = [element]
        numIons = [int(number)]

    factor = options.factor
    if factor < 0:
        print("Error: Volume factor must be greater than 0.")
        sys.exit(0)

    verbosity = options.verbosity
    attempts = options.attempts
    outdir = options.outdir
    dimension = options.dimension
    thickness = options.thickness

    try:
        os.mkdir(outdir)
    except: pass

    filecount = 1 #To check whether a file already exists
    for i in range(attempts):
        numIons0 = np.array(numIons)
        sg = options.sg
        start = time()
        if dimension == 3:
            rand_crystal = random_crystal(options.sg, system, numIons0, factor)
            sg1 = sg
        elif dimension == 2:
            rand_crystal = random_crystal_2D(options.sg, system, numIons0, thickness, factor)
            sg1 = rand_crystal.sg
        elif dimension == 1:
            rand_crystal = random_crystal_1D(options.sg, system, numIons0, thickness, factor)
            sg1 = "?"
        if dimension == 0:
            rand_crystal = random_cluster(options.sg, system, numIons0, factor)
            sg1 = sg
        end = time()
        timespent = np.around((end - start), decimals=2)

        if rand_crystal.valid:
            #Output a cif file
            written = False
            try:
                comp = str(rand_crystal.struct.composition)
                comp = comp.replace(" ", "")
                cifpath = outdir + '/' + comp + "_" + str(filecount) + '.cif'
                while os.path.isfile(cifpath):
                    filecount += 1
                    cifpath = outdir + '/' + comp + "_" + str(filecount) + '.cif'
                CifWriter(rand_crystal.struct, symprec=0.1).write_file(filename = cifpath)
                written = True
            except: pass
            #POSCAR output
            #rand_crystal.struct.to(fmt="poscar", filename = '1.vasp')

            #spglib style structure called cell
            ans = get_symmetry_dataset(rand_crystal.spg_struct, symprec=1e-1)['number']
            print('Space group  requested:', sg1, ' generated:', ans)
            if written is True:
                print("    Output to "+cifpath)
            else:
                print("    Could not write cif file.")

            #Print additional information about the structure
            if verbosity > 0:
                print("Time required for generation: " + str(timespent) + "s")
                print(rand_crystal.struct)


        #If generation fails
        else: 
            print('something is wrong')
            print('Time spent during generation attempt: ' + str(timespent) + "s")
