from pkg_resources import resource_filename

from math import sqrt

import numpy as np
from scipy.spatial.distance import cdist

from pymatgen.symmetry.groups import sg_symbol_from_int_number
from pymatgen.symmetry.analyzer import generate_full_symmops
from pymatgen.core.operations import SymmOp

from pandas import read_csv

from pyxtal.operations import *

#Define variables
#------------------------------
Euclidean_lattice = np.array([[1,0,0],[0,1,0],[0,0,1]])
letters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

wyckoff_df = read_csv(resource_filename("pyxtal", "database/wyckoff_list.csv"))
wyckoff_symmetry_df = read_csv(resource_filename("pyxtal", "database/wyckoff_symmetry.csv"))
wyckoff_generators_df = read_csv(resource_filename("pyxtal", "database/wyckoff_generators.csv"))
layer_df = read_csv(resource_filename("pyxtal", "database/layer.csv"))
layer_symmetry_df = read_csv(resource_filename("pyxtal", "database/layer_symmetry.csv"))
layer_generators_df = read_csv(resource_filename("pyxtal", "database/layer_generators.csv"))
rod_df = read_csv(resource_filename("pyxtal", "database/rod.csv"))
rod_symmetry_df = read_csv(resource_filename("pyxtal", "database/rod_symmetry.csv"))
rod_generators_df = read_csv(resource_filename("pyxtal", "database/rod_generators.csv"))
point_df = read_csv(resource_filename("pyxtal", "database/point.csv"))
point_symmetry_df = read_csv(resource_filename("pyxtal", "database/point_symmetry.csv"))
point_generators_df = read_csv(resource_filename("pyxtal", "database/point_generators.csv"))

pi = np.pi

Identity = SymmOp.from_xyz_string('x,y,z')
Inversion = SymmOp.from_xyz_string('-x,-y,-z')
op_o = SymmOp.from_xyz_string('0,0,0')
op_x = SymmOp.from_xyz_string('x,0,0')
op_y = SymmOp.from_xyz_string('0,y,0')
op_z = SymmOp.from_xyz_string('0,0,z')

pglist = ['C1','Ci','C2','Cs','C2h','D2','C2v','D2h',
    'C4','S4','C4h','D4','C4v','D2d','D4h','C3',
    'C3i','D3','C3v','D3d','C6','C3h','C6h','D6',
    'C6v','D3h','D6h','T','Th','O','Td','Oh']

#TODO: Add space, layer, and Rod group symbol lists

#Define functions
#------------------------------
def symmetry_element_from_axis(axis):
    """
    Given an axis, returns a SymmOp representing a symmetry element on the axis.
    For example, the symmetry element for the vector (0,0,2) would be (0,0,z).
    
    Args:
        axis: a 3-vector representing the symmetry element

    Returns:
        a SymmOp object of form (ax, bx, cx), (ay, by, cy), or (az, bz, cz)
    """
    if len(axis) != 3:
        return
    #Vector must be non-zero
    if dsquared(axis) < 1e-6:
        return
    v = np.array(axis) / np.linalg.norm(axis)
    #Find largest component (x, y, or z)
    abs_vals = [abs(a) for a in v]
    f1 = max(abs_vals)
    index1 = list(abs_vals).index(f1)
    #Initialize an affine matrix
    m = np.eye(4)
    m[:3] = [0.,0.,0.,0.]
    #Set values for affine matrix
    m[:3,index1] = v
    return SymmOp(m)

def create_matrix(PBC=[1,1,1]):
    """
    Used for calculating distances in lattices with periodic boundary
    conditions. When multiplied with a set of points, generates additional
    points in cells adjacent to and diagonal to the original cell

    Args:
        PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
            Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis

    Returns:
        A numpy array of matrices which can be multiplied by a set of
        coordinates
    """
    matrix = []
    i_list = [-1, 0, 1]
    j_list = [-1, 0, 1]
    k_list = [-1, 0, 1]
    if not PBC[0]:
        i_list = [0]
    if not PBC[1]:
        j_list = [0]
    if not PBC[2]:
        k_list = [0]
    for i in i_list:
        for j in j_list:
            for k in k_list:
                matrix.append([i,j,k])
    return np.array(matrix, dtype=float)

def filtered_coords(coords, PBC=[1,1,1]):
    """
    Given an array of 3d fractional coordinates or a single 3d point, transform
    all coordinates to less than 1 and greater than 0. If one axis is not
    periodic, does not transform the coordinates along that axis. For example,
    for the point [1.2,1.6, -.4] with periodicity along the x and z axes, but
    not the y axis (PBC=[1,0,1]), the function would return [0.2, 1.6, 0.6].

    Args:
        coords: an array of real 3d vectors. The shape does not matter
        PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
            Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis

    Returns:
        an array of filtered coords with the same shape as coords
    """
    def filter_vector(vector):
        f = np.floor(vector)
        return vector - np.multiply(f, PBC)

    return np.apply_along_axis(filter_vector, -1, coords)

def filtered_coords_euclidean(coords, PBC=[1,1,1]):
    """
    Given an array of fractional 3-vectors, filters coordinates to between 0 and
    1. Then, values which are greater than 0.5 are converted to 1 minus their
    value. This is used for converting displacement vectors with a Euclidean
    lattice.
    
    Args:
        coords: an array of real 3d vectors. The shape does not matter
        PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
            Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis

    Returns:
        an array of filtered coords with the same shape as coords
    """
    def filter_vector_euclidean(vector):
        for i, a in enumerate(PBC):
            if a:
                vector[i] -= np.floor(vector[i])
                if vector[i] > 0.5:
                    vector[i] = 1 - vector[i]
        return vector

    return np.apply_along_axis(filter_vector_euclidean, -1, coords)

def distance(xyz, lattice, PBC=[1,1,1]):
    """
    Returns the Euclidean distance from the origin for a fractional
    displacement vector. Takes into account the lattice metric and periodic
    boundary conditions, including up to one non-periodic axis.
    
    Args:
        xyz: a fractional 3d displacement vector. Can be obtained by
            subtracting one fractional vector from another
        lattice: a 3x3 matrix describing a unit cell's lattice vectors
        PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
            Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis

    Returns:
        a scalar for the distance of the point from the origin
    """
    xyz = filtered_coords(xyz, PBC=PBC)
    matrix = create_matrix(PBC=PBC)
    matrix += xyz
    matrix = np.dot(matrix, lattice)
    return np.min(cdist(matrix,[[0,0,0]]))     

def dsquared(v):
    """
    Returns the squared length of a 3-vector. Does not consider PBC.

    Args:
        v: a 3-vector
    
    Returns:
        the squared length of the vector
    """
    return v[0]**2 + v[1]**2 + v[2]**2

def distance_matrix(points1, points2, lattice, PBC=[1,1,1], metric='euclidean'):
    """
    Returns the distances between two sets of fractional coordinates.
    Takes into account the lattice metric and periodic boundary conditions.
    
    Args:
        points1: a list of fractional coordinates
        points2: another list of fractional coordinates
        lattice: a 3x3 matrix describing a unit cell's lattice vectors
        PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
            Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis
        metric: the metric to use with cdist. Possible values include 'euclidean',
            'sqeuclidean', 'minkowski', and others

    Returns:
        a 2x2 np array of scalar distances
    """
    l1 = filtered_coords(points1, PBC=PBC)
    l2 = filtered_coords(points2, PBC=PBC)
    l2 = np.dot(l2, lattice)
    matrix = create_matrix(PBC=PBC)
    m1 = np.array([(l1 + v) for v in matrix])
    m1 = np.dot(m1, lattice)
    all_distances = np.array([cdist(l, l2, metric) for l in m1])
    return np.apply_along_axis(np.min, 0, all_distances)

def distance_matrix_euclidean(points1, points2, PBC=[1,1,1], squared=False):
    """
    Returns the distances between two sets of fractional coordinates.
    Takes into account periodic boundary conditions, but assumes a Euclidean matrix.
    
    Args:
        points1: a list of fractional coordinates
        points2: another list of fractional coordinates
        PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
            Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis
        squared: whether to return the squared distance (True) or the Euclidean distance (False)

    Returns:
        a 2x2 np array of scalar distances
    """
    def subtract(p):
        return points2 - p
    #get displacement vectors
    displacements = filtered_coords_euclidean(np.apply_along_axis(subtract, -1, points1), PBC=PBC)
    #Calculate norms
    if squared is True:
        return np.apply_along_axis(dsquared, -1, displacements)
    else:
        return np.apply_along_axis(np.linalg.norm, -1, displacements)

def get_wyckoffs(sg, organized=False, PBC=[1,1,1]):
    """
    Returns a list of Wyckoff positions for a given space group. Has option to
    organize the list based on multiplicity (this is used for
    random_crystal.wyckoffs) For an unorganized list:

    1st index: index of WP in sg (0 is the WP with largest multiplicity)

    2nd index: a SymmOp object in the WP

    For an organized list:

    1st index: specifies multiplicity (0 is the largest multiplicity)

    2nd index: corresponds to a Wyckoff position within the group of equal
        multiplicity.

    3nd index: corresponds to a SymmOp object within the Wyckoff position

    You may switch between organized and unorganized lists using the methods
    i_from_jk and jk_from_i. For example, if a Wyckoff position is the [i]
    entry in an unorganized list, it will be the [j][k] entry in an organized
    list.

    Args:
        sg: the international spacegroup number
        organized: whether or not to organize the list based on multiplicity
        PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
            Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis
    
    Returns: 
        a list of Wyckoff positions, each of which is a list of SymmOp's
    """
    if PBC != [1,1,1]:
        coor = [0,0,0]
        for i, a in enumerate(PBC):
            if not a:
                coor[i] = 0.5
        coor = np.array(coor)

    wyckoff_strings = eval(wyckoff_df["0"][sg])
    wyckoffs = []
    for x in wyckoff_strings:
        if PBC != [1,1,1]:
            op = SymmOp.from_xyz_string(x[0])
            coor1 = op.operate(coor)
            invalid = False
            for i, a in enumerate(PBC):
                if not a:
                    if not abs(coor1[i]-0.5) < 1e-2:
                        #invalid wyckoffs for layer group
                        invalid = True
            if invalid is False:
                wyckoffs.append([])
                for y in x:
                    wyckoffs[-1].append(SymmOp.from_xyz_string(y))
        else:
            wyckoffs.append([])
            for y in x:
                wyckoffs[-1].append(SymmOp.from_xyz_string(y))
    if organized:
        wyckoffs_organized = [[]] #2D Array of WP's organized by multiplicity
        old = len(wyckoffs[0])
        for wp in wyckoffs:
            mult = len(wp)
            if mult != old:
                wyckoffs_organized.append([])
                old = mult
            wyckoffs_organized[-1].append(wp)
        return wyckoffs_organized
    else:
        return wyckoffs

def get_layer(num, organized=False):
    """
    Returns a list of Wyckoff positions for a given 2D layer group. Has
    option to organize the list based on multiplicity (this is used for
    random_crystal_2D.wyckoffs) For an unorganized list:

    1st index: index of WP in layer group (0 is the WP with largest multiplicity)

    2nd index: a SymmOp object in the WP

    For an organized list:

    1st index: specifies multiplicity (0 is the largest multiplicity)

    2nd index: corresponds to a Wyckoff position within the group of equal
        multiplicity.

    3nd index: corresponds to a SymmOp object within the Wyckoff position

    You may switch between organized and unorganized lists using the methods
    i_from_jk and jk_from_i. For example, if a Wyckoff position is the [i]
    entry in an unorganized list, it will be the [j][k] entry in an organized
    list.

    For layer groups with more than one possible origin, origin choice 2 is
    used.

    Args:
        num: the international layer group number
        organized: whether or not to organize the list based on multiplicity
    
    Returns: 
        a list of Wyckoff positions, each of which is a list of SymmOp's
    """
    wyckoff_strings = eval(layer_df["0"][num])
    wyckoffs = []
    for x in wyckoff_strings:
        wyckoffs.append([])
        for y in x:
            wyckoffs[-1].append(SymmOp.from_xyz_string(y))
    if organized:
        wyckoffs_organized = [[]] #2D Array of WP's organized by multiplicity
        old = len(wyckoffs[0])
        for wp in wyckoffs:
            mult = len(wp)
            if mult != old:
                wyckoffs_organized.append([])
                old = mult
            wyckoffs_organized[-1].append(wp)
        return wyckoffs_organized
    else:
        return wyckoffs

def get_rod(num, organized=False):
    """
    Returns a list of Wyckoff positions for a given 1D Rod group. Has option to
    organize the list based on multiplicity (this is used for
    random_crystal_1D.wyckoffs) For an unorganized list:

    1st index: index of WP in layer group (0 is the WP with largest multiplicity)

    2nd index: a SymmOp object in the WP

    For an organized list:

    1st index: specifies multiplicity (0 is the largest multiplicity)

    2nd index: corresponds to a Wyckoff position within the group of equal
        multiplicity.

    3nd index: corresponds to a SymmOp object within the Wyckoff position

    You may switch between organized and unorganized lists using the methods
    i_from_jk and jk_from_i. For example, if a Wyckoff position is the [i]
    entry in an unorganized list, it will be the [j][k] entry in an organized
    list.

    For Rod groups with more than one possible setting, setting choice 1
    is used.

    Args:
        num: the international Rod group number
        organized: whether or not to organize the list based on multiplicity
    
    Returns: 
        a list of Wyckoff positions, each of which is a list of SymmOp's
    """
    wyckoff_strings = eval(rod_df["0"][num])
    wyckoffs = []
    for x in wyckoff_strings:
        wyckoffs.append([])
        for y in x:
            wyckoffs[-1].append(SymmOp.from_xyz_string(y))
    if organized:
        wyckoffs_organized = [[]] #2D Array of WP's organized by multiplicity
        old = len(wyckoffs[0])
        for wp in wyckoffs:
            mult = len(wp)
            if mult != old:
                wyckoffs_organized.append([])
                old = mult
            wyckoffs_organized[-1].append(wp)
        return wyckoffs_organized
    else:
        return wyckoffs

def get_point(num, organized=False, molecular=True):
    """
    Returns a list of Wyckoff positions for a given crystallographic point group.
    Has option to organize the list based on multiplicity.

    1st index: index of WP in layer group (0 is the WP with largest multiplicity)

    2nd index: a SymmOp object in the WP

    For point groups except T, Th, O, Td, and Oh, unique axis z is used.

    Args:
        num: the point group number (see bottom of source code for a list)
        organized: whether or not to organize the list based on multiplicity
        molecular: whether or not to convert to Euclidean reference frame
            (for hexagonal lattices: point groups 16-27)
    
    Returns: 
        a list of Wyckoff positions, each of which is a list of SymmOp's
    """
    P = SymmOp.from_rotation_and_translation([[1,-.5,0],[0,math.sqrt(3)/2,0],[0,0,1]], [0,0,0])
    convert = False
    if molecular is True:
        if num in range(16,28):
            convert = True
    wyckoff_strings = eval(point_df["0"][num])
    wyckoffs = []
    for x in wyckoff_strings:
        wyckoffs.append([])
        for y in x:

            op = SymmOp.from_xyz_string(y)
            if convert is True:
                #Convert non-orthogonal trigonal/hexagonal operations
                op = P*op*P.inverse
            if molecular is False:
                wyckoffs[-1].append(op)
            elif molecular is True:
                op = SymmOp.from_rotation_and_translation(op.rotation_matrix,[0,0,0])
                wyckoffs[-1].append(op)

    if organized:
        wyckoffs_organized = [[]] #2D Array of WP's organized by multiplicity
        old = len(wyckoffs[0])
        for wp in wyckoffs:
            mult = len(wp)
            if mult != old:
                wyckoffs_organized.append([])
                old = mult
            wyckoffs_organized[-1].append(wp)
        return wyckoffs_organized
    else:
        return wyckoffs

def get_wyckoff_symmetry(sg, PBC=[1,1,1], molecular=False):
    """
    Returns a list of Wyckoff position site symmetry for a given space group.
    1st index: index of WP in sg (0 is the WP with largest multiplicity)
    2nd index: a point within the WP
    3rd index: a site symmetry SymmOp of the point

    Args:
        sg: the international spacegroup number
        PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
            Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis
        molecular: whether or not to return the Euclidean point symmetry
            operations. If True, cuts off translational part of operation, and
            converts non-orthogonal operations (3-fold and 6-fold rotations)
            to (orthogonal) pure rotations. Should be used when dealing with
            molecular crystals

    Returns:
        a 3d list of SymmOp objects representing the site symmetry of each
        point in each Wyckoff position
    """
    if PBC != [1,1,1]:
        coor = [0,0,0]
        for i, a in enumerate(PBC):
            if not a:
                coor[i] = 0.5
        coor = np.array(coor)
    wyckoffs = get_wyckoffs(sg, PBC=PBC)

    P = SymmOp.from_rotation_and_translation([[1,-.5,0],[0,math.sqrt(3)/2,0],[0,0,1]], [0,0,0])
    symmetry_strings = eval(wyckoff_symmetry_df["0"][sg])
    symmetry = []
    convert = False
    if molecular is True:
        if sg >= 143 and sg <= 194:
            convert = True
    #Loop over Wyckoff positions
    for x, w in zip(symmetry_strings, wyckoffs):
        if PBC != [1,1,1]:
            op = w[0]
            coor1 = op.operate(coor)
            invalid = False
            for i, a in enumerate(PBC):
                if not a:
                    if not abs(coor1[i]-0.5) < 1e-2:
                        invalid = True
            if invalid == False:
                symmetry.append([])
                #Loop over points in WP
                for y in x:
                    symmetry[-1].append([])
                    #Loop over ops
                    for z in y:
                        op = SymmOp.from_xyz_string(z)
                        if convert is True:
                            #Convert non-orthogonal trigonal/hexagonal operations
                            op = P*op*P.inverse
                        if molecular is False:
                            symmetry[-1][-1].append(op)
                        elif molecular is True:
                            op = SymmOp.from_rotation_and_translation(op.rotation_matrix,[0,0,0])
                            symmetry[-1][-1].append(op)
        else:
            symmetry.append([])
            #Loop over points in WP
            for y in x:
                symmetry[-1].append([])
                #Loop over ops
                for z in y:
                    op = SymmOp.from_xyz_string(z)
                    if convert is True:
                        #Convert non-orthogonal trigonal/hexagonal operations
                        op = P*op*P.inverse
                    if molecular is False:
                        symmetry[-1][-1].append(op)
                    elif molecular is True:
                        op = SymmOp.from_rotation_and_translation(op.rotation_matrix,[0,0,0])
                        symmetry[-1][-1].append(op)
    return symmetry

def get_layer_symmetry(num, molecular=False):
    """
    Returns a list of Wyckoff position site symmetry for a given space group.
    1st index: index of WP in group (0 is the WP with largest multiplicity)
    2nd index: a point within the WP
    3rd index: a site symmetry SymmOp of the point

    Args:
        num: the layer group number
        molecular: whether or not to return the Euclidean point symmetry
            operations. If True, cuts off translational part of operation, and
            converts non-orthogonal operations (3-fold and 6-fold rotations)
            to (orthogonal) pure rotations. Should be used when dealing with
            molecular crystals

    Returns:
        a 3d list of SymmOp objects representing the site symmetry of each
        point in each Wyckoff position
    """

    P = SymmOp.from_rotation_and_translation([[1,-.5,0],[0,math.sqrt(3)/2,0],[0,0,1]], [0,0,0])
    symmetry_strings = eval(layer_symmetry_df["0"][num])
    symmetry = []
    convert = False
    if molecular is True:
        if num >= 65:
            convert = True
    #Loop over Wyckoff positions
    for x in symmetry_strings:
        symmetry.append([])
        #Loop over points in WP
        for y in x:
            symmetry[-1].append([])
            #Loop over ops
            for z in y:
                op = SymmOp.from_xyz_string(z)
                if convert is True:
                    #Convert non-orthogonal trigonal/hexagonal operations
                    op = P*op*P.inverse
                if molecular is False:
                    symmetry[-1][-1].append(op)
                elif molecular is True:
                    op = SymmOp.from_rotation_and_translation(op.rotation_matrix,[0,0,0])
                    symmetry[-1][-1].append(op)
    return symmetry

def get_rod_symmetry(num, molecular=False):
    """
    Returns a list of Wyckoff position site symmetry for a given Rod group.
    1st index: index of WP in group (0 is the WP with largest multiplicity)
    2nd index: a point within the WP
    3rd index: a site symmetry SymmOp of the point

    Args:
        num: the Rod group number
        molecular: whether or not to return the Euclidean point symmetry
            operations. If True, cuts off translational part of operation, and
            converts non-orthogonal operations (3-fold and 6-fold rotations)
            to (orthogonal) pure rotations. Should be used when dealing with
            molecular crystals

    Returns:
        a 3d list of SymmOp objects representing the site symmetry of each
        point in each Wyckoff position
    """

    P = SymmOp.from_rotation_and_translation([[1,-.5,0],[0,math.sqrt(3)/2,0],[0,0,1]], [0,0,0])
    symmetry_strings = eval(rod_symmetry_df["0"][num])
    symmetry = []
    convert = False
    if molecular is True:
        if num >= 42:
            convert = True
    #Loop over Wyckoff positions
    for x in symmetry_strings:
        symmetry.append([])
        #Loop over points in WP
        for y in x:
            symmetry[-1].append([])
            #Loop over ops
            for z in y:
                op = SymmOp.from_xyz_string(z)
                if convert is True:
                    #Convert non-orthogonal trigonal/hexagonal operations
                    op = P*op*P.inverse
                if molecular is False:
                    symmetry[-1][-1].append(op)
                elif molecular is True:
                    op = SymmOp.from_rotation_and_translation(op.rotation_matrix,[0,0,0])
                    symmetry[-1][-1].append(op)
    return symmetry

def get_point_symmetry(num, molecular=True):
    """
    Returns a list of Wyckoff position site symmetry for a given point group.
    1st index: index of WP in group (0 is the WP with largest multiplicity)
    2nd index: a point within the WP
    3rd index: a site symmetry SymmOp of the point

    Args:
        num: the point group number
        molecular: whether or not to convert to Euclidean reference frame
            (for hexagonal lattices: point groups 16-27)

    Returns:
        a 3d list of SymmOp objects representing the site symmetry of each
        point in each Wyckoff position
    """
    P = SymmOp.from_rotation_and_translation([[1,-.5,0],[0,math.sqrt(3)/2,0],[0,0,1]], [0,0,0])
    symmetry_strings = eval(point_symmetry_df["0"][num])
    symmetry = []
    convert = False
    if molecular is True:
        if num in range(16,28):
            convert = True
    #Loop over Wyckoff positions
    for x in symmetry_strings:
        symmetry.append([])
        #Loop over points in WP
        for y in x:
            symmetry[-1].append([])
            #Loop over ops
            for z in y:
                op = SymmOp.from_xyz_string(z)
                if convert is True:
                    #Convert non-orthogonal trigonal/hexagonal operations
                    op = P*op*P.inverse
                if molecular is False:
                    symmetry[-1][-1].append(op)
                elif molecular is True:
                    op = SymmOp.from_rotation_and_translation(op.rotation_matrix,[0,0,0])
                    symmetry[-1][-1].append(op)
    return symmetry

def get_wyckoff_generators(sg, PBC=[1,1,1], molecular=False):
    """
    Returns a list of Wyckoff generators for a given space group.
    1st index: index of WP in sg (0 is the WP with largest multiplicity)
    2nd index: a generator for the WP
    This function is useful for rotating molecules based on Wyckoff position,
    since special Wyckoff positions only encode positional information, but not
    information about the orientation. The generators for each Wyckoff position
    form a subset of the spacegroup's general Wyckoff position.
    
    Args:
        sg: the international spacegroup number
        PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
            Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis
        molecular: whether or not to return the Euclidean point symmetry
            operations. If True, cuts off translational part of operation, and
            converts non-orthogonal operations (3-fold and 6-fold rotations)
            to (orthogonal) pure rotations. Should be used when dealing with
            molecular crystals
    
    Returns:
        a 2d list of SymmOp objects which can be used to generate a Wyckoff position given a
        single fractional (x,y,z) coordinate
    """
    if PBC != [1,1,1]:
        coor = [0,0,0]
        for i, a in enumerate(PBC):
            if not a:
                coor[i] = 0.5
        coor = np.array(coor)
    wyckoffs = get_wyckoffs(sg, PBC=PBC)

    P = SymmOp.from_rotation_and_translation([[1,-.5,0],[0,math.sqrt(3)/2,0],[0,0,1]], [0,0,0])
    generator_strings = eval(wyckoff_generators_df["0"][sg])
    generators = []
    convert = False
    if molecular is True:
        if sg >= 143 and sg <= 194:
            convert = True
    #Loop over Wyckoff positions
    for x, w in zip(generator_strings, wyckoffs):
        if PBC != [1,1,1]:
            op = w[0]
            coor1 = op.operate(coor)
            invalid = False
            for i, a in enumerate(PBC):
                if not a:
                    if not abs(coor1[i]-0.5) < 1e-2:
                        invalid = True
            if invalid == False:
                generators.append([])
                #Loop over ops
                for y in x:
                    op = SymmOp.from_xyz_string(y)
                    if convert is True:
                        #Convert non-orthogonal trigonal/hexagonal operations
                        op = P*op*P.inverse
                    if molecular is False:
                        generators[-1].append(op)
                    elif molecular is True:
                        op = SymmOp.from_rotation_and_translation(op.rotation_matrix,[0,0,0])
                        generators[-1].append(op)
        else:
            generators.append([])
            for y in x:
                op = SymmOp.from_xyz_string(y)
                if convert is True:
                    #Convert non-orthogonal trigonal/hexagonal operations
                    op = P*op*P.inverse
                if molecular is False:
                    generators[-1].append(op)
                elif molecular is True:
                    op = SymmOp.from_rotation_and_translation(op.rotation_matrix,[0,0,0])
                    generators[-1].append(op)
    return generators

def get_layer_generators(num, molecular=False):
    """
    Returns a list of Wyckoff generators for a given layer group.
    1st index: index of WP in group (0 is the WP with largest multiplicity)
    2nd index: a generator for the WP
    This function is useful for rotating molecules based on Wyckoff position,
    since special Wyckoff positions only encode positional information, but not
    information about the orientation. The generators for each Wyckoff position
    form a subset of the group's general Wyckoff position.
    
    Args:
        num: the layer group number
        molecular: whether or not to return the Euclidean point symmetry
            operations. If True, cuts off translational part of operation, and
            converts non-orthogonal operations (3-fold and 6-fold rotations)
            to (orthogonal) pure rotations. Should be used when dealing with
            molecular crystals
    
    Returns:
        a 2d list of SymmOp objects which can be used to generate a Wyckoff position given a
        single fractional (x,y,z) coordinate
    """

    P = SymmOp.from_rotation_and_translation([[1,-.5,0],[0,math.sqrt(3)/2,0],[0,0,1]], [0,0,0])
    generator_strings = eval(layer_generators_df["0"][num])
    generators = []
    convert = False
    if molecular is True:
        if num >= 65:
            convert = True
    #Loop over Wyckoff positions
    for x in generator_strings:
        generators.append([])
        #Loop over ops
        for y in x:
            op = SymmOp.from_xyz_string(y)
            if convert is True:
                #Convert non-orthogonal trigonal/hexagonal operations
                op = P*op*P.inverse
            if molecular is False:
                generators[-1].append(op)
            elif molecular is True:
                op = SymmOp.from_rotation_and_translation(op.rotation_matrix,[0,0,0])
                generators[-1].append(op)
    return generators

def get_rod_generators(num, molecular=False):
    """
    Returns a list of Wyckoff generators for a given Rod group.
    1st index: index of WP in group (0 is the WP with largest multiplicity)
    2nd index: a generator for the WP
    This function is useful for rotating molecules based on Wyckoff position,
    since special Wyckoff positions only encode positional information, but not
    information about the orientation. The generators for each Wyckoff position
    form a subset of the group's general Wyckoff position.
    
    Args:
        num: the Rod group number
        molecular: whether or not to return the Euclidean point symmetry
            operations. If True, cuts off translational part of operation, and
            converts non-orthogonal operations (3-fold and 6-fold rotations)
            to (orthogonal) pure rotations. Should be used when dealing with
            molecular crystals
    
    Returns:
        a 2d list of SymmOp objects which can be used to generate a Wyckoff position given a
        single fractional (x,y,z) coordinate
    """

    P = SymmOp.from_rotation_and_translation([[1,-.5,0],[0,math.sqrt(3)/2,0],[0,0,1]], [0,0,0])
    generator_strings = eval(rod_generators_df["0"][num])
    generators = []
    convert = False
    if molecular is True:
        if num >= 42:
            convert = True
    #Loop over Wyckoff positions
    for x in generator_strings:
        generators.append([])
        #Loop over ops
        for y in x:
            op = SymmOp.from_xyz_string(y)
            if convert is True:
                #Convert non-orthogonal trigonal/hexagonal operations
                op = P*op*P.inverse
            if molecular is False:
                generators[-1].append(op)
            elif molecular is True:
                op = SymmOp.from_rotation_and_translation(op.rotation_matrix,[0,0,0])
                generators[-1].append(op)
    return generators

def get_point_generators(num, molecular=True):
    """
    Returns a list of Wyckoff generators for a given point group.
    1st index: index of WP in group (0 is the WP with largest multiplicity)
    2nd index: a generator for the WP
    This function is useful for rotating molecules based on Wyckoff position,
    since special Wyckoff positions only encode positional information, but not
    information about the orientation. The generators for each Wyckoff position
    form a subset of the group's general Wyckoff position.
    
    Args:
        num: the Rod group number
        molecular: whether or not to convert to Euclidean reference frame
            (for hexagonal lattices: point groups 16-27)
    
    Returns:
        a 2d list of SymmOp objects which can be used to generate a Wyckoff position given a
        single fractional (x,y,z) coordinate
    """
    P = SymmOp.from_rotation_and_translation([[1,-.5,0],[0,math.sqrt(3)/2,0],[0,0,1]], [0,0,0])
    generator_strings = eval(point_generators_df["0"][num])
    generators = []
    convert = False
    if molecular is True:
        if num in range(16,28):
            convert = True
    #Loop over Wyckoff positions
    for x in generator_strings:
        generators.append([])
        #Loop over ops
        for y in x:
            op = SymmOp.from_xyz_string(y)
            if convert is True:
                #Convert non-orthogonal trigonal/hexagonal operations
                op = P*op*P.inverse
            if molecular is False:
                generators[-1].append(op)
            elif molecular is True:
                op = SymmOp.from_rotation_and_translation(op.rotation_matrix,[0,0,0])
                generators[-1].append(op)
    return generators

def general_position(number, dim=3):
    """
    Returns a Wyckoff_position object for the general Wyckoff position of the given
    group.

    Args:
        number: the international number of the group
        dim: the dimension of the group 3: space group, 2: layer group, 1: Rod group

    Returns:
        a Wyckoff_position object for the general position
    """
    return Wyckoff_position.from_group_and_index(number, 0, dim=dim)

def site_symm(point, gen_pos, tol=1e-3, lattice=Euclidean_lattice, PBC=None):
    """
    Given a point and a general Wyckoff position, return the list of symmetry
    operations leaving the point (coordinate or SymmOp) invariant. The returned
    SymmOps are a subset of the general position. The site symmetry can be used
    for determining the Wyckoff position for a set of points, or for
    determining the valid orientations of a molecule within a given Wyckoff
    position.

    Args:
        point: a 1x3 coordinate or SymmOp object to find the symmetry of. If a
            SymmOp is given, the returned symmetries must also preserve the
            point's orientaion
        gen_pos: the general position of the spacegroup. Can be a Wyckoff_position
            object or list of SymmOp objects.
            Can be obtained using general_position()
        tol:
            the numberical tolerance for determining equivalent positions and
            orientations.
        lattice:
            a 3x3 matrix representing the lattice vectors of the unit cell
        PBC: A periodic boundary condition list, where 1 means periodic, 0 means not periodic.
            Ex: [1,1,1] -> full 3d periodicity, [0,0,1] -> periodicity along the z axis.
            Need not be defined here if gen_pos is a Wyckoff_position object.

    Returns:
        a list of SymmOp objects which leave the given point invariant
    """
    if PBC == None:
        if type(gen_pos) == Wyckoff_position:
            PBC = gen_pos.PBC
        else:
            PBC=[1,1,1]
    #Convert point into a SymmOp
    if type(point) != SymmOp:
        point = SymmOp.from_rotation_and_translation([[0,0,0],[0,0,0],[0,0,0]], np.array(point))
    symmetry = []
    for op in gen_pos:
        is_symmetry = True
        #Calculate the effect of applying op to point
        difference = SymmOp((op*point).affine_matrix - point.affine_matrix)
        #Check that the rotation matrix is unaltered by op
        if not np.allclose(difference.rotation_matrix, np.zeros((3,3)), rtol = 1e-3, atol = 1e-3):
            is_symmetry = False
        #Check that the displacement is less than tol
        displacement = difference.translation_vector
        if distance(displacement, lattice, PBC=PBC) > tol:
            is_symmetry = False
        if is_symmetry:
            """The actual site symmetry's translation vector may vary from op by
            a factor of +1 or -1 (especially when op contains +-1/2).
            We record this to distinguish between special Wyckoff positions.
            As an example, consider the point (-x+1/2,-x,x+1/2) in position 16c
            of space group Ia-3(206). The site symmetry includes the operations
            (-z+1,x-1/2,-y+1/2) and (y+1/2,-z+1/2,-x+1). These operations are
            not listed in the general position, but correspond to the operations
            (-z,x+1/2,-y+1/2) and (y+1/2,-z+1/2,-x), respectively, just shifted
            by (+1,-1,0) and (0,0,+1), respectively.
            """
            el = SymmOp.from_rotation_and_translation(op.rotation_matrix, op.translation_vector - np.round(displacement))
            symmetry.append(el)
    return symmetry

def find_generating_point(coords, wyckoff_position):
    """
    Given a set of coordinates and Wyckoff generators, return the coord which
    can be used to generate the others. This is useful for molecular Wyckoff
    positions, for which the orientation, and not just the position, is
    needed for each point in the Wyckoff position. Thus, we need to know which
    coordinates to use for x, y, and z, so that rotations can be applied
    correctly using the Wyckoff geneators

    Args:
        coords: a list of fractional coordinates corresponding to a Wyckoff
            position
        wyckoff_position: a Wyckoff_position object
    
    Returns:
        a fractional coordinate [x, y, z] corresponding to the first listed
        point in the Wyckoff position
     """
    generators = wyckoff_position.generators
    PBC = wyckoff_position.PBC
    for coord in coords:
        if not np.allclose(coord, generators[0].operate(coord)):
            continue
        tmp_c = deepcopy(coords)
        tmp_c = filtered_coords(tmp_c, PBC=PBC)
        generated = list(gen.operate(coord) for gen in generators)
        generated = filtered_coords(generated, PBC=PBC)
        index_list1 = list(range(len(tmp_c)))
        index_list2 = list(range(len(generated)))
        if len(generated) != len(tmp_c):
            print("Warning: coordinate and generator lists have unequal length.")
            print("In check_wyckoff_position.find_generating_point:")
            print("len(coords): "+str(len(coords))+", len(generators): "+str(len(generators)))
            return None
        for index1, c1 in enumerate(tmp_c):
            for index2, c2 in enumerate(generated):
                if np.allclose(c1, c2, atol=.001, rtol=.001):
                    if index1 in index_list1 and index2 in index_list2:
                        index_list1.remove(index1)
                        index_list2.remove(index2)
                        break
        if index_list2 == []:
            return coord
    #If no valid coordinate is found
    return None

def check_wyckoff_position(points, group, tol=1e-3):
    """
    Given a list of points, returns a single index of a matching Wyckoff
    position in the space group. Checks the site symmetry of each supplied
    point against the site symmetry for each point in the Wyckoff position.
    Also returns a point which can be used to generate the rest using the
    Wyckoff position operators

    Args:
        points: a list of 3d coordinates or SymmOps to check
        group: a Group object
        tol: the max distance between equivalent points

    Returns:
        index, p: index is a single index for the Wyckoff position within
        the sg. If no matching WP is found, returns False. point is a
        coordinate taken from the list points. When plugged into the Wyckoff
        position, it will generate all the other points.
    """
    wyckoffs = group.wyckoffs
    w_symm_all = group.w_symm
    PBC = group.PBC
    #new method
    #Store the squared distance tolerance
    t = tol**2
    #Loop over Wyckoff positions
    for i, wp in enumerate(wyckoffs):
        #Check that length of points and wp are equal
        if len(wp) != len(points): continue
        failed = False

        #Search for a generating point
        for p in points:
            failed = False
            #Check that point works as x,y,z value for wp
            xyz = filtered_coords_euclidean(wp[0].operate(p) - p, PBC=PBC)

            if dsquared(xyz) > t: continue
            #Calculate distances between original and generated points
            pw = np.array([op.operate(p) for op in wp])
            dw = distance_matrix_euclidean(points, pw, PBC=PBC, squared=True)

            #Check each row for a zero
            for row in dw:
                num = (row < t).sum()
                if num < 1:
                    failed = True
                    break

            if failed is True: continue
            #Check each column for a zero
            for column in dw.T:
                num = (column < t).sum()
                if num < 1:
                    failed = True
                    break

            #Calculate distance between original and generated points
            ps = np.array([op.operate(p) for op in w_symm_all[i][0]])
            ds = distance_matrix_euclidean([p], ps, PBC=PBC, squared=True)
            #Check whether any generated points are too far away
            num = (ds > t).sum()
            if num > 0:
                failed = True

            if failed is True: continue
            return i, p
    return False, None

#TODO: Use Group object instead of organized array
def letter_from_index(index, arr):
    """
    Given a Wyckoff position's index within a spacegroup, return its number
    and letter e.g. '4a'

    Args:
        index: a single integer describing the WP's index within the
            spacegroup (0 is the general position)
        arr: an unorganized Wyckoff position array
   
    Returns:
        the Wyckoff letter corresponding to the Wyckoff position (for example,
        for position 4a, the function would return 'a')
    """
    length = len(arr)
    return letters[length - 1 - index]

def index_from_letter(letter, arr):
    """
    Given the Wyckoff letter, returns the index of a Wyckoff position within
    the spacegroup

    Args:
        letter: The wyckoff letter
        arr: an unorganized Wyckoff position array

    Returns:
        a single index specifying the location of the Wyckoff position within
        the spacegroup (0 is the general position)
    """
    length = len(arr)
    return length - 1 - letters.index(letter)

def jk_from_i(i, olist):
    """
    Given an organized list (Wyckoff positions or orientations), determine the
    two indices which correspond to a single index for an unorganized list.
    Used mainly for organized Wyckoff position lists, but can be used for other
    lists organized in a similar way

    Args:
        i: a single index corresponding to the item's location in the
            unorganized list
        olist: the organized list

    Returns:
        [j, k]: two indices corresponding to the item's location in the
            organized list
    """
    num = -1
    found = False
    for j , a in enumerate(olist):
        for k , b in enumerate(a):
            num += 1
            if num == i:
                return [j, k]
    print("Error: Incorrect Wyckoff position list or index passed to jk_from_i")
    return None

def i_from_jk(j, k, olist):
    """
    Inverse operation of jk_from_i: gives one list index from 2

    Args:
        j, k: indices corresponding to the location of an element in the
            organized list
        olist: the organized list of Wyckoff positions or molecular orientations

    Returns:
        i: one index corresponding to the item's location in the
            unorganized list    
    """
    num = -1
    for x, a in enumerate(olist):
        for y, b in enumerate(a):
            num += 1
            if x == j and y == k:
                return num
    print("Error: Incorrect Wyckoff position list or index passed to jk_from_i")
    return None

def ss_string_from_ops(ops, number, dim=3, complete=True):
    """
    Print the Hermann-Mauguin symbol for a site symmetry group, using a list of
    SymmOps as input. Note that the symbol does not necessarily refer to the
    x,y,z axes. For information on reading these symbols, see:
    http://en.wikipedia.org/wiki/Hermann-Mauguin_notation#Point_groups

    Args:
        ops: a list of SymmOp objects representing the site symmetry
        number: International number of the symmetry group. Used to determine which
            axes to show. For example, a 3-fold rotation in a cubic system is
            written as ".3.", whereas a 3-fold rotation in a trigonal system is
            written as "3.."
        dim: the dimension of the crystal. Also used to determine notation type
        complete: whether or not all symmetry operations in the group
            are present. If False, we generate the rest

    Returns:
        a string representing the site symmetry. Ex: "2mm"
    """
    #TODO: Automatically detect which symm_type to use based on ops
    #Determine which notation to use
    symm_type = "high"
    if dim == 3:
        if number >= 1 and number <= 74:
            #Triclinic, monoclinic, orthorhombic
            symm_type = "low"
        elif number >= 75 and number <= 194:
            #Trigonal, Hexagonal, Tetragonal
            symm_type = "medium"
        elif number >= 195 and number <= 230:
            #cubic
            symm_type = "high"
    if dim == 2:
        if number >= 1 and number <= 48:
            #Triclinic, monoclinic, orthorhombic
            symm_type = "low"
        elif number >= 49 and number <= 80:
            #Trigonal, Hexagonal, Tetragonal
            symm_type = "medium"
    if dim == 1:
        if number >= 1 and number <= 22:
            #Triclinic, monoclinic, orthorhombic
            symm_type = "low"
        elif number >= 23 and number <= 75:
            #Trigonal, Hexagonal, Tetragonal
            symm_type = "medium"

    #TODO: replace sg with number, add dim variable
    #Return the symbol for a single axis
    #Will be called later in the function
    def get_symbol(opas, order, has_reflection):
        #ops: a list of Symmetry operations about the axis
        #order: highest order of any symmetry operation about the axis
        #has_reflection: whether or not the axis has mirror symmetry
        if has_reflection is True:
            #rotations have priority
            for opa in opas:
                if opa.order == order and opa.type == "rotation":
                    return str(opa.rotation_order)+"/m"
            for opa in opas:
                if (opa.order == order and opa.type == "rotoinversion"
                    and opa.order != 2):
                    return "-"+str(opa.rotation_order)
            return "m"
        elif has_reflection is False:
            #rotoinversion has priority
            for opa in opas:
                if opa.order == order and opa.type == "rotoinversion":
                    return "-"+str(opa.rotation_order)
            for opa in opas:
                if opa.order == order and opa.type == "rotation":
                    return str(opa.rotation_order)
            return "."
    #Given a list of single-axis symbols, return the one with highest symmetry
    #Will be called later in the function
    def get_highest_symbol(symbols):
        symbol_list = ['.','2','m','-2','2/m','3','4','-4','4/m','-3','6','-6','6/m']
        max_index = 0
        use_list = True
        for j, symbol in enumerate(symbols):
            if symbol in symbol_list:
                i = symbol_list.index(symbol)
            else:
                use_list = False
                num_str = ''.join(c for c in symbol if c.isdigit())
                i1 = int(num_str)
                if 'm' in symbol or '-' in symbol:
                    if i1 % 2 == 0:
                        i = i1
                    elif i1 % 2 == 1:
                        i = i1 * 2
            if i > max_index:
                max_j = j
                max_index = i
        if use_list is True:
            return symbol_list[max_index]
        else:
            return symbols[max_j]
        
    #Return whether or not two axes are symmetrically equivalent
    #It is assumed that both axes possess the same symbol
    #Will be called within combine_axes
    def are_symmetrically_equivalent(index1, index2):
        axis1 = axes[index1]
        axis2 = axes[index2]
        condition1 = False
        condition2 = False
        #Check for an operation mapping one axis onto the other
        for op in ops:
            if condition1 is False or condition2 is False:
                new1 = op.operate(axis1)
                new2 = op.operate(axis2)
                if np.isclose(abs(np.dot(new1, axis2)), 1):
                    condition1 = True
                if np.isclose(abs(np.dot(new2, axis1)), 1):
                    condition2 = True
        if condition1 is True and condition2 is True:
            return True
        else:
            return False
    #Given a list of axis indices, return the combined symbol
    #Axes may or may not be symmetrically equivalent, but must be of the same
    #type (x/y/z, face-diagonal, body-diagonal)
    #Will be called for mid- and high-symmetry crystallographic point groups
    def combine_axes(indices):
        symbols = {}
        for index in deepcopy(indices):
            symbol = get_symbol(params[index],orders[index],reflections[index])
            if symbol == ".":
                indices.remove(index)
            else:
                symbols[index] = symbol
        if indices == []:
            return "."
        #Remove redundant axes
        for i in deepcopy(indices):
            for j in deepcopy(indices):
                if j > i:
                    if symbols[i] == symbols[j]:
                        if are_symmetrically_equivalent(i, j):
                            if j in indices:
                                indices.remove(j)
        #Combine symbols for non-equivalent axes
        new_symbols = []
        for i in indices:
            new_symbols.append(symbols[i])
        symbol = ""
        while new_symbols != []:
            highest = get_highest_symbol(new_symbols)
            symbol += highest
            new_symbols.remove(highest)
        if symbol == "":
            print("Error: could not combine site symmetry axes.")
            return
        else:
            return symbol
    #Generate needed ops
    if complete is False:
        ops = generate_full_symmops(ops, 1e-3)
    #Get OperationAnalyzer object for all ops
    opas = []
    for op in ops:
        opas.append(OperationAnalyzer(op))
    #Store the symmetry of each axis
    params = [[],[],[],[],[],[],[],[],[],[],[],[],[]]
    has_inversion = False
    #Store possible symmetry axes for crystallographic point groups
    axes = [[1,0,0],[0,1,0],[0,0,1],
            [1,1,0],[0,1,1],[1,0,1],[1,-1,0],[0,1,-1],[1,0,-1],
            [1,1,1],[-1,1,1],[1,-1,1],[1,1,-1]]
    for i, axis in enumerate(axes):
        axes[i] = axis/np.linalg.norm(axis)
    for opa in opas:
        if opa.type != "identity" and opa.type != "inversion":
            found = False
            for i, axis in enumerate(axes):
                if np.isclose(abs(np.dot(opa.axis, axis)), 1):
                    found = True
                    params[i].append(opa)
            #Store uncommon axes for trigonal and hexagonal lattices
            if found is False:
                axes.append(opa.axis)
                #Check that new axis is not symmetrically equivalent to others
                unique = True
                for i, axis in enumerate(axes):
                    if i != len(axes)-1:
                        if are_symmetrically_equivalent(i, len(axes)-1):
                            unique = False
                if unique is True:
                    params.append([opa])
                elif unique is False:
                    axes.pop()
        elif opa.type == "inversion":
            has_inversion = True
    #Determine how many high-symmetry axes are present
    n_axes = 0
    #Store the order of each axis
    orders = []
    #Store whether or not each axis has reflection symmetry
    reflections = []
    for axis in params:
        order = 1
        high_symm = False
        has_reflection = False
        for opa in axis:
            if opa.order >= 3:
                high_symm = True
            if opa.order > order:
                order = opa.order
            if opa.order == 2 and opa.type == "rotoinversion":
                has_reflection = True
        orders.append(order)
        if high_symm == True:
            n_axes += 1
        reflections.append(has_reflection)
    #Triclinic, monoclinic, orthorhombic
    #Positions in symbol refer to x,y,z axes respectively
    if symm_type == "low":
        symbol = (get_symbol(params[0], orders[0], reflections[0])+
                get_symbol(params[1], orders[1], reflections[1])+
                get_symbol(params[2], orders[2], reflections[2]))
        if symbol != "...":
            return symbol
        elif symbol == "...":
            if has_inversion is True:
                return "-1"
            else:
                return "1"
    #Trigonal, Hexagonal, Tetragonal
    elif symm_type == "medium":
        #1st symbol: z axis
        s1 = get_symbol(params[2], orders[2], reflections[2])
        #2nd symbol: x or y axes (whichever have higher symmetry)
        s2 = combine_axes([0,1])
        #3rd symbol: face-diagonal axes (whichever have highest symmetry)
        s3 = combine_axes(list(range(3, len(axes))))
        symbol = s1+" "+s2+" "+s3
        if symbol != ". . .":
            return symbol
        elif symbol == ". . .":
            if has_inversion is True:
                return "-1"
            else:
                return "1"
    #Cubic
    elif symm_type == "high":
        pass
        #1st symbol: x, y, and/or z axes (whichever have highest symmetry)
        s1 = combine_axes([0,1,2])
        #2nd symbol: body-diagonal axes (whichever has highest symmetry)
        s2 = combine_axes([9,10,11,12])
        #3rd symbol: face-diagonal axes (whichever have highest symmetry)
        s3 = combine_axes([3,4,5,6,7,8])
        symbol = s1+" "+s2+" "+s3
        if symbol != ". . .":
            return symbol
        elif symbol == ". . .":
            if has_inversion is True:
                return "-1"
            else:
                return "1"
    else:
        print("Error: invalid spacegroup number")
        return

def symbol_from_number(number, symbol):
    """
    Returns the H-M symbol for a given international group number
    """
    #TODO: Create database/lists of symbols for groups
    pass

def organized_wyckoffs(group):
    """
    Takes a Group object or unorganized list of Wyckoff positions and returns
    a 2D list of Wyckoff positions organized by multiplicity.

    Args:
        group: a pyxtal.symmetry.Group object
    
    Returns:
        a 2D list of Wyckoff_position objects if group is a Group object.
        a 3D list of SymmOp objects if group is a 2D list of SymmOps
    """
    if type(group) == Group:
        wyckoffs = group.Wyckoff_positions
    else:
        wyckoffs = group
    wyckoffs_organized = [[]] #2D Array of WP's organized by multiplicity
    old = len(wyckoffs[0])
    for wp in wyckoffs:
        mult = len(wp)
        if mult != old:
            wyckoffs_organized.append([])
            old = mult
        wyckoffs_organized[-1].append(wp)
    return wyckoffs_organized

class Wyckoff_position():
    """
    Class for a single Wyckoff position within a symmetry group
    """
    def from_dict(dictionary):
        """
        Constructs a Wyckoff_position object using a dictionary. Used mainly by the
        Wyckoff class for constructing a list of Wyckoff_position objects at once
        """
        wp = Wyckoff_position()
        for key in dictionary:
            setattr(wp, key, dictionary[key])
        return wp

    def __str__(self):
        try:
            return self.string
        except:
            if self.dim not in list(range(4)):
                return "Error: invalid crystal dimension. Must be a number between 0 and 3."
            s = "Wyckoff position "+str(self.multiplicity)+self.letter+" in "
            if self.dim == 3:
                s += "space "
            elif self.dim == 2:
                s += "layer "
            elif self.dim == 1:
                s += "Rod "
            elif self.dim == 0:
                s += "Point group " + self.symbol
            if self.dim != 0:
                s += "group " + str(self.number)
            s += " with site symmetry "+ss_string_from_ops(self.symmetry_m[0], self.number, dim=self.dim)
            for op in self.ops:
                s += "\n" + op.as_xyz_string()
            self.string = s
            return self.string

    def __repr__(self):
        return str(self)

    def from_group_and_index(group, index, dim=3, PBC=None):
        """
        Creates a Wyckoff_position using the space group number and index
        
        Args:
            group: the international number of the symmetry group
            index: the index or letter of the Wyckoff position within the group.
                0 is always the general position, and larger indeces represent positions
                with lower multiplicity. Alternatively, index can be the Wyckoff letter
                ("4a6" or "f")
            dim: the periodic dimension of the crystal
            PBC: the periodic boundary conditions
        """
        wp = Wyckoff_position()
        wp.dim = dim
        if type(group) == int:
            wp.number = group
            number = group
        else:
            #TODO: add symbol interpretation
            print("Error: must use an integer group number.")
            return
        use_letter = False
        if type(index) == int:
            wp.index = index
        elif type(index) == str:
            use_letter = True
            #Extract letter from number-letter combinations ("4d"->"d")
            for c in index:
                if c.isalpha():
                    index = c
                    break

        if dim == 3:
            if number not in range(1, 231):
                print("Error: invalid symmetry group "+str(group)+" for dimension "+str(self.dim))
                return
            if PBC == None:
                wp.PBC = [1,1,1]
            else:
                wp.PBC = PBC
            ops_all = get_wyckoffs(wp.number)
            if use_letter is True:
                wp.index = index_from_letter(index, ops_all)
                wp.letter = index
            else:
                wp.letter = letter_from_index(wp.index, ops_all)
            if wp.index >= len(ops_all) or wp.index < 0:
                print("Error while generating Wyckoff_position: index out of range for specified group")
                return
            wp.ops = ops_all[wp.index]
            """The Wyckoff positions for the crystal's spacegroup."""
            wp.multiplicity = len(wp.ops)
            wp.symmetry = get_wyckoff_symmetry(wp.number)[wp.index]
            """A list of site symmetry operations for the Wyckoff positions, obtained
                from get_wyckoff_symmetry (molecular=False)"""
            wp.symmetry_m = get_wyckoff_symmetry(wp.number, molecular=True)[wp.index]
            """A list of site symmetry operations for the Wyckoff positions, obtained
                from get_wyckoff_symmetry (molecular=False)"""
            wp.generators = get_wyckoff_generators(wp.number)[wp.index]
            """A list of Wyckoff generators (molecular=False)"""
            wp.generators_m = get_wyckoff_generators(wp.number, molecular=True)[wp.index]
            """A list of Wyckoff generators (molecular=True)"""

        elif dim == 2:
            if number not in range(1, 81):
                print("Error: invalid symmetry group "+str(group)+" for dimension "+str(self.dim))
                return
            if PBC == None:
                wp.PBC = [1,1,0]
            else:
                wp.PBC = PBC
            ops_all = get_layer(wp.number)
            if use_letter is True:
                wp.index = index_from_letter(index, ops_all)
                wp.letter = index
            else:
                wp.letter = letter_from_index(wp.index, ops_all)
            if wp.index >= len(ops_all) or wp.index < 0:
                print("Error while generating Wyckoff_position: index out of range for specified group")
                return
            wp.ops = ops_all[wp.index]
            """The Wyckoff positions for the crystal's spacegroup."""
            wp.multiplicity = len(wp.ops)
            wp.symmetry = get_layer_symmetry(wp.number)[wp.index]
            """A list of site symmetry operations for the Wyckoff positions, obtained
                from get_wyckoff_symmetry (molecular=False)"""
            wp.symmetry_m = get_layer_symmetry(wp.number, molecular=True)[wp.index]
            """A list of site symmetry operations for the Wyckoff positions, obtained
                from get_wyckoff_symmetry (molecular=False)"""
            wp.generators = get_layer_generators(wp.number)[wp.index]
            """A list of Wyckoff generators (molecular=False)"""
            wp.generators_m = get_layer_generators(wp.number, molecular=True)[wp.index]
            """A list of Wyckoff generators (molecular=True)"""

        elif dim == 1:
            if number not in range(1, 76):
                print("Error: invalid symmetry group "+str(group)+" for dimension "+str(self.dim))
                return
            if PBC == None:
                wp.PBC = [0,0,1]
            else:
                wp.PBC = PBC
            ops_all = get_rod(wp.number)
            if use_letter is True:
                wp.index = index_from_letter(index, ops_all)
                wp.letter = index
            else:
                wp.letter = letter_from_index(wp.index, ops_all)
            if wp.index >= len(ops_all) or wp.index < 0:
                print("Error while generating Wyckoff_position: index out of range for specified group")
                return
            wp.ops = ops_all[wp.index]
            """The Wyckoff positions for the crystal's spacegroup."""
            wp.multiplicity = len(wp.ops)
            wp.symmetry = get_rod_symmetry(wp.number)[wp.index]
            """A list of site symmetry operations for the Wyckoff positions, obtained
                from get_wyckoff_symmetry (molecular=False)"""
            wp.symmetry_m = get_rod_symmetry(wp.number, molecular=True)[wp.index]
            """A list of site symmetry operations for the Wyckoff positions, obtained
                from get_wyckoff_symmetry (molecular=False)"""
            wp.generators = get_rod_generators(wp.number)[wp.index]
            """A list of Wyckoff generators (molecular=False)"""
            wp.generators_m = get_rod_generators(wp.number, molecular=True)[wp.index]
            """A list of Wyckoff generators (molecular=True)"""

        elif dim == 0:
            #TODO: implement Clusters
            return Wyckoff_position.from_dict({"dim": 0})
        return wp

    def wyckoff_from_generating_op(gen_op, gen_pos):
        """
        Given a general position and generating operation (ex: "x,0,0"), returns a
        Wyckoff_position object.
        
        Args:
            gen_op: a SymmOp into which the generating coordinate will be plugged
            gen_pos: a list of SymmOps representing the general position

        Returns:
            a list of SymmOps
        """
        new_ops = [op*gen_op for op in gen_pos]
        return list(set(new_ops))
    
    def symmetry_from_wyckoff(wp, gen_pos):
        symm = []
        for op in wp:
            symm.append(site_symm(op, gen_pos))
        return symm

    def __iter__(self):
        yield from self.ops

    def __getitem__(self, index):
        return self.ops[index]

    def __len__(self):
        return self.multiplicity

    def get_site_symmetry(self):
        return ss_string_from_ops(self.symmetry_m[0], self.number, dim=self.dim)

class Group():
    """
    Class for storing a set of Wyckoff positions for a symmetry group. See the documentation
    for details about settings.

    Args:
        group: the group symbol or international number
        dim: the periodic dimension of the group
    """
    def __str__(self):
        try:
            return self.string
        except:
            if self.dim == 0:
                #TODO: implement point group symbols
                s = "-- Point group " + self.symbol + " --"
            elif self.dim == 3:
                s = "-- Space "
            elif self.dim == 2:
                s = "-- Layer "
            elif self.dim == 1:
                s = "-- Rod "
            else:
                return "Error: invalid crystal dimension. Must be a number between 0 and 3."
            if self.dim != 0:
                s += "group # "+str(self.number)+" ("+self.symbol+")--"
            #TODO: implement H-M symbol
            #s += symbol_from_number(self.number, dim=self.dim)
            for wp in self.Wyckoff_positions:
                s += "\n  "+str(wp.multiplicity)+wp.letter+"\tsite symm: " + ss_string_from_ops(wp.symmetry_m[0], self.number, dim=self.dim)
                #for op in wp.ops:
                #    s += "\n" + op.as_xyz_string()
            self.string = s
            return self.string

    def __repr__(self):
        return str(self)
        
    def __init__(self, group, dim=3):
        self.dim = dim
        #TODO: get symbol from number
        self.symbol = str(group)
        if type(group) == int:
            self.number = group
            number = group
        elif type(group) == str:
            #TODO: add symbol interpretation
            if dim != 0:
                print("Cannot currently interpret symbols for Rod, layer, and space groups.")
                print("Please use an integer.")
                return
            elif dim == 0:
                symbol = group
                if group in pglist:
                    self.symbol = symbol
                    number = self.number = group = pglist.index(group) + 1
                else:
                    number = self.number = None
        else:
            print("Error: Please input a symbol (str) or integer (int) for the group.")
            return
        if dim == 3:
            if number not in range(1, 231):
                print("Error: invalid symmetry group "+str(group)+" for dimension "+str(self.dim))
                return
            self.PBC = [1,1,1]
            self.wyckoffs = get_wyckoffs(self.number)
            """The Wyckoff positions for the crystal's spacegroup."""
            self.w_symm = get_wyckoff_symmetry(self.number)
            """A list of site symmetry operations for the Wyckoff positions, obtained
                from get_wyckoff_symmetry (molecular=False)"""
            self.w_symm_m = get_wyckoff_symmetry(self.number, molecular=True)
            """A list of site symmetry operations for the Wyckoff positions, obtained
                from get_wyckoff_symmetry (molecular=True)"""
            self.wyckoff_generators = get_wyckoff_generators(self.number)
            """A list of Wyckoff generators (molecular=False)"""
            self.wyckoff_generators_m = get_wyckoff_generators(self.number, molecular=True)
            """A list of Wyckoff generators (molecular=True)"""
            if self.number <= 2:
                self.lattice_type = "triclinic"
            elif self.number <= 15:
                self.lattice_type = "monoclinic"
            elif self.number <= 74:
                self.lattice_type = "orthorhombic"
            elif self.number <= 142:
                self.lattice_type = "tetragonal"
            elif self.number <= 194:
                self.lattice_type = "hexagonal"
            elif self.number <= 230:
                self.lattice_type = "cubic"
        elif dim == 2:
            if number not in range(1, 81):
                print("Error: invalid symmetry group "+str(group)+" for dimension "+str(self.dim))
                return
            self.PBC = [1,1,0]
            self.wyckoffs = get_layer(self.number)
            """The Wyckoff positions for the crystal's spacegroup."""
            self.w_symm = get_layer_symmetry(self.number)
            """A list of site symmetry operations for the Wyckoff positions, obtained
                from get_wyckoff_symmetry (molecular=False)."""
            self.w_symm_m = get_layer_symmetry(self.number, molecular=True)
            """A list of site symmetry operations for the Wyckoff positions, obtained
                from get_wyckoff_symmetry (molecular=True)"""
            self.wyckoff_generators = get_layer_generators(self.number)
            """A list of Wyckoff generators (molecular=False)"""
            self.wyckoff_generators_m = get_layer_generators(self.number, molecular=True)
            """A list of Wyckoff generators (molecular=True)"""
            if self.number <= 2:
                self.lattice_type = "triclinic"
            elif self.number <= 18:
                self.lattice_type = "monoclinic"
            elif self.number <= 48:
                self.lattice_type = "orthorhombic"
            elif self.number <= 64:
                self.lattice_type = "tetragonal"
            elif self.number <= 80:
                self.lattice_type = "hexagonal"
        elif dim == 1:
            if number not in range(1, 76):
                print("Error: invalid symmetry group "+str(group)+" for dimension "+str(self.dim))
                return
            self.PBC = [0,0,1]
            self.wyckoffs = get_rod(self.number)
            """The Wyckoff positions for the crystal's spacegroup."""
            self.w_symm = get_rod_symmetry(self.number)
            """A list of site symmetry operations for the Wyckoff positions, obtained
                from get_wyckoff_symmetry (molecular=False)"""
            self.w_symm_m = get_rod_symmetry(self.number, molecular=True)
            """A list of site symmetry operations for the Wyckoff positions, obtained
                from get_wyckoff_symmetry (molecular=True)"""
            self.wyckoff_generators = get_rod_generators(self.number)
            """A list of Wyckoff generators (molecular=False)"""
            self.wyckoff_generators_m = get_rod_generators(self.number, molecular=True)
            """A list of Wyckoff generators (molecular=True)"""
            if self.number <= 2:
                self.lattice_type = "triclinic"
            elif self.number <= 12:
                self.lattice_type = "monoclinic"
            elif self.number <= 22:
                self.lattice_type = "orthorhombic"
            elif self.number <= 41:
                self.lattice_type = "tetragonal"
            elif self.number <= 75:
                self.lattice_type = "hexagonal"
        elif dim == 0:
            #0-D clusters. Except for group "I" and "Ih", z axis is the high-symmetry axis
            #https://en.wikipedia.org/wiki/Schoenflies_notation#Point_groups
            self.dim = 0
            self.PBC = [0,0,0]
            #Check if string is for crystallographic point group
            if type(group) == str:
                if group in pglist:
                    group = pglist.index(group) + 1
            #Get crystallographic point group
            if type(group) == int or type(group) == float:
                if number not in range(1, 33):
                    print("Error: invalid symmetry group "+str(group)+" for dimension "+str(self.dim))
                    return
                self.PBC = [0,0,0]
                self.wyckoffs = get_point(self.number, molecular=False)
                """The Wyckoff positions for the crystal's spacegroup."""
                self.w_symm = get_point_symmetry(self.number, molecular=False)
                """A list of site symmetry operations for the Wyckoff positions, obtained
                    from get_wyckoff_symmetry (molecular=False)"""
                self.w_symm_m = get_point_symmetry(self.number)
                """A list of site symmetry operations for the Wyckoff positions, obtained
                    from get_wyckoff_symmetry (molecular=True)"""
                self.wyckoff_generators = get_point_generators(self.number, molecular=False)
                """A list of Wyckoff generators (molecular=False)"""
                self.wyckoff_generators_m = get_point_generators(self.number)
                """A list of Wyckoff generators (molecular=True)"""
                if self.number <= 15:
                    self.lattice_type = "cylindrical"
                elif self.number <= 27:
                    self.lattice_type = "cylindrical"
                elif self.number <= 32:
                    self.lattice_type = "spherical"
            #Get other point groups
            else:
                #Remove whitespace
                symbol = ''.join(c for c in symbol if not c.isspace())
                #Find rotation order from symbol
                num_str = ''.join(c for c in symbol if not c.isalpha())
                if num_str == "*":
                    num = 0 #infinite rotation order
                elif num_str == "":
                    num = 1 #No rotation order
                else:
                    try:
                        num = int(num_str) #rotation order
                        1 / num
                    except:
                        print("Error: invalid rotation order for point group symbol.")
                        return
                gens = [SymmOp.from_xyz_string('x,y,z')] # List of generator SymmOps
                generate = True
                #interpret symbol
                if symbol[0] == "I":
                    #Icosohedral
                    self.lattice_type = "spherical"
                    self.number = None

                    #Add 2, 3, and 5-fold rotations
                    gens.append(SymmOp.from_xyz_string('-x,-y,z'))
                    gens.append(SymmOp.from_xyz_string('z,x,y'))
                    tau = 0.5*(sqrt(5)+1)
                    m = aa2matrix([1., tau, 0.], 2*pi/5)
                    gens.append(SymmOp.from_rotation_and_translation(m, [0,0,0]))

                    #Add Wyckoff generating operations
                    op_c = SymmOp.from_xyz_string('x,0,0')
                    op_b = SymmOp.from_xyz_string('x,x,x')
                    m = [[0,0,0,0],[0,1,0,0],[0,tau,0,0],[0,0,0,0]]
                    op_a = SymmOp(m)
                    gen_ops = [Identity, op_c, op_b, op_a, op_o]

                    if symbol == "Ih":
                        #Add horizontal mirror plane
                        mirror = SymmOp.from_xyz_string('x,y,-z') #m x,y,0
                        gen_pos = generate_full_symmops([R2, R3, R5, mirror], .03)
                        op_d = SymmOp.from_xyz_string('0,y,z')
                        gen_ops = [Identity, op_d, op_c, op_b, op_a, op_o]
                elif symbol[0] == "C" and symbol[-1] != "i":
                    #n-fold rotation
                    self.lattice_type = "cylindrical"
                    if symbol[-1] == "d":
                        print("Error: Invalid point group symbol.")
                        return
                    if num == 0:
                        #infinite-order rotation
                        self.symbol = "C*"
                        generate=False
                        pass
                    else:
                        #Add rotation
                        self.symbol = "C" + str(num)
                        m = aa2matrix([0.,0.,1.], 2*pi/num)
                        gens.append(SymmOp.from_rotation_and_translation(m, [0.,0.,0.]))
                        op_c = SymmOp.from_xyz_string('x,-x,z')
                        op_b = SymmOp.from_xyz_string('x,0,z')
                        gen_ops = [Identity, op_z]
                    if symbol[-1] == "v":
                        #Add vertical mirror plane
                        gens.append(SymmOp.from_xyz_string('-x,y,z')) #m 0,y,z
                        self.symbol += "v"
                        if num % 2 == 1:
                            gen_ops = [Identity, op_c, op_z]
                        elif num % 2 == 0:
                            gen_ops = [Identity, op_c, op_b, op_z]
                    if symbol[-1] == "h":
                        #Add horizontal mirror plane
                        gens.append(SymmOp.from_xyz_string('x,y,-z')) #m x,y,0
                        self.symbol += "h"
                        op_xy = SymmOp.from_xyz_string('x,y,0')
                        gen_ops = [Identity, op_xy, op_z, op_o]
                elif symbol[0] == "C" and symbol[-1] == "i":
                    #n-fold rotinversion, usually just Ci
                    self.lattice_type = "cylindrical"
                    if "d" in symbol or "h" in symbol or "v" in symbol:
                        print("Error: Invalid point group symbol.")
                        return
                    if num == 0:
                        #infinite-order rotation
                        gens.append(SymmOp.from_xyz_string('-x,-y,-z'))
                        gens.append(SymmOp.from_xyz_string('x,y,-z'))
                        self.symbol = "C*i"
                        generate = False
                    else:
                        #Add rotoinversion
                        m = np.dot(aa2matrix([0.,0.,1.], 2*pi/num), [[-1.,0.,0.],[0.,-1.,0.],[0.,0.,-1.]])
                        gens.append(SymmOp.from_rotation_and_translation(m, [0.,0.,0.]))
                        if num == 1:
                            self.symbol = "Ci"
                        else:
                            self.symbol = "C" + str(num) + "i"
                        gen_ops = [Identity, op_z, op_o]
                elif symbol[0] == "D":
                    #n-fold rotation and n 2-fold perpendicular rotations
                    self.lattice_type = "cylindrical"
                    if num == 0:
                        #infinite-order rotation
                        self.symbol = "D*"
                        generate = False
                    else:
                        #Add rotation
                        self.symbol = "D" + str(num)
                        #Rotation angle
                        angle = 2*pi/num
                        m = aa2matrix([0.,0.,1.], angle)
                        gens.append(SymmOp.from_rotation_and_translation(m, [0.,0.,0.]))
                        #Different group orders have different multiplicities for "D" point groups
                        gen_ops = [Identity]
                        if num % 2 == 0:
                            #Add (x,0,0)
                            gen_ops.append(op_x)
                            num2 = num // 2
                            if num2 % 2 == 0:
                                #Add num-fold symmetry axis
                                axis = np.dot(m, [1,0,0])
                            elif num2 % 2 == 1:
                                #Add num2-fold symmetry axis
                                m = aa2matrix([0.,0.,1.], 0.5*angle)
                                axis = np.dot(m, [1,0,0])
                        elif num % 2 == 1:
                            #Add num-fold symmetry axis
                            axis = np.dot(m, [1,0,0])
                        if symbol[-1] == "d":
                            #Add half-angle reflection operation
                            m_ref = [[np.cos(angle),np.sin(angle),0],[np.sin(angle),-np.cos(angle),0],[0,0,1]]
                            gens.append(SymmOp.from_rotation_and_translation(m_ref, [0.,0.,0.]))
                            self.symbol += "d"
                            #Add (x,0,z)
                            gen_ops.append(SymmOp.from_xyz_string('x,0,z'))
                            if num % 2 == 0:
                                #Add symmetry element + z
                                m0 = symmetry_element_from_axis(axis).affine_matrix
                                m0[2] = [0,0,1,0]
                                new_op = SymmOp(m0)
                                gen_ops.append(new_op)
                        elif symbol[-1] == "h":
                            #Add horizontal mirror plane
                            gens.append(SymmOp.from_xyz_string('x,y,-z')) #m x,y,0
                            self.symbol += "h"
                            gen_ops.append(SymmOp.from_xyz_string('x,y,0'))
                            if num % 2 == 0:
                                #Add (x,0,z)
                                gen_ops.append(SymmOp.from_xyz_string('x,0,z'))
                            #Add symmetry axis + z
                            m0 = symmetry_element_from_axis(axis).affine_matrix
                            m0[2] = [0,0,1,0]
                            new_op = SymmOp(m0)
                            gen_ops.append(new_op)
                        #Add generator op for axis, as well as z-axis and origin
                        gen_ops += [op_z, op_o]

                    if self.symbol == "D*" or symbol[-1]=="v" or symbol[-1]=="i":
                        print("Error: invalid point group symbol.")
                        return
                elif symbol[0] == "S":
                    #2n-fold rotation-reflection axis
                    self.lattice_type = "cylindrical"
                    #Equivalent to Cnh for odd n
                    if num == 0 or symbol[-1]=="v" or symbol[-1]=="i" or symbol[-1]=="h" or symbol[-1]=="d":
                        print("Error: invalid point group symbol.")
                        return
                    m = np.dot(aa2matrix([0.,0.,1.], 2*pi/num), [[1.,0.,0.],[0.,1.,0.],[0.,0.,-1.]])
                    gens.append(SymmOp.from_rotation_and_translation(m, [0.,0.,0.]))
                    if num % 2 == 1:
                        op_xy = SymmOp.from_xyz_string('x,y,0')
                        gen_ops = [Identity, op_xy, op_z, op_o]
                    elif num % 2 == 0:
                        gen_ops = [Identity, op_z, op_o]
                else:
                    print("Error: Invalid point group symbol.")
                    return
                #Generate full set of SymmOps
                if generate is True:
                    gen_pos = generate_full_symmops(gens, 0.03)
                if "*" not in self.symbol:
                    #Calculate Wyckoff positions
                    self.wyckoffs = []
                    for op in gen_ops:
                        wp = Wyckoff_position.wyckoff_from_generating_op(op, gen_pos)
                        if wp[0] != op:
                            index = wp.index(op)
                            op2 = wp[0]
                            wp[index] = op2
                            wp[0] = op
                        self.wyckoffs.append(wp)
                    #Calculate site symmetry and generators
                    self.w_symm = []
                    for wp in self.wyckoffs:
                        self.w_symm.append(Wyckoff_position.symmetry_from_wyckoff(wp, gen_pos))
                    self.w_symm_m = deepcopy(self.w_symm)
                    self.wyckoff_generators = deepcopy(self.wyckoffs)
                    self.wyckoff_generators_m = deepcopy(self.wyckoffs)
                elif "*" in self.symbol:
                    #infinite rotational groups
                    if self.symbol == "C*":
                        self.wyckoffs = [[SymmOp.from_xyz_string('0,0,z')]]
                        self.w_symm = [[[SymmOp.from_xyz_string('x,y,z')]]]
                        self.w_symm_m = deepcopy(self.w_symm)
                        self.wyckoff_generators = deepcopy(self.wyckoffs)
                        self.wyckoff_generators_m = deepcopy(self.wyckoffs)
                    elif self.symbol == "C*h":
                        self.wyckoffs = [[op_z, SymmOp.from_xyz_string('0,0,-z')],[op_o]]
                        self.w_symm = [[[SymmOp.from_xyz_string('x,y,z')]],[[SymmOp.from_xyz_string('0,0,-z')]]]
                        self.w_symm_m = deepcopy(self.w_symm)
                        self.wyckoff_generators = deepcopy(self.wyckoffs)
                        self.wyckoff_generators_m = deepcopy(self.wyckoffs)
                    elif self.symbol == "C*v":
                        self.wyckoffs = [[SymmOp.from_xyz_string('0,0,z')]]
                        self.w_symm = [[[SymmOp.from_xyz_string('x,y,z')]]]
                        self.w_symm_m = deepcopy(self.w_symm)
                        self.wyckoff_generators = deepcopy(self.wyckoffs)
                        self.wyckoff_generators_m = deepcopy(self.wyckoffs)
                    elif self.symbol == "D*h":
                        self.wyckoffs = [[op_z, SymmOp.from_xyz_string('0,0,-z')],[op_o]]
                        self.w_symm = [[[SymmOp.from_xyz_string('x,y,z')]],[[SymmOp.from_xyz_string('0,0,-z')]]]
                        self.w_symm_m = deepcopy(self.w_symm)
                        self.wyckoff_generators = deepcopy(self.wyckoffs)
                        self.wyckoff_generators_m = deepcopy(self.wyckoffs)
                    else:
                        print("Error: Invalid point group symbol.")
                self.number = None
            
        #TODO: Add self.symbol to dictionary
        wpdicts = [{"index": i, "letter": letter_from_index(i, self.wyckoffs), "ops": self.wyckoffs[i],
            "multiplicity": len(self.wyckoffs[i]), "symmetry": self.w_symm[i], "symmetry_m": self.w_symm_m[i],
            "generators": self.wyckoff_generators[i], "generators_m": self.wyckoff_generators_m[i],
            "PBC": self.PBC, "dim": self.dim, "number": self.number, "symbol": self.symbol} for i in range(len(self.wyckoffs))]
        self.Wyckoff_positions = [Wyckoff_position.from_dict(wpdict) for wpdict in wpdicts]
        """A list of Wyckoff_position objects, sorted by descending multiplicity"""
        self.wyckoffs_organized = organized_wyckoffs(self)
        """A 2D list of Wyckoff_position objects, grouped and sorted by
        multiplicity."""
    
    def get_wyckoff_position(self, index):
        """
        Returns a single Wyckoff_position object
        
        Args:
            index: the index of the Wyckoff position within the group
                The largest position is always 0

        Returns: a Wyckoff_position object
        """
        if type(index) == int:
            pass
        elif type(index) == str:
            #Extract letter from number-letter combinations ("4d"->"d")
            for c in index:
                if c.isalpha():
                    letter = c
                    break
            index = index_from_letter(letter, self.wyckoffs)
        return self.Wyckoff_positions[index]

    def get_wyckoff_symmetry(self, index, molecular=False):
        """
        Returns the site symmetry symbol for the Wyckoff position

        Args:
            index: the index of the Wyckoff position within the group
                The largest position is always 0
            molecular: whether to use the Euclidean operations or not (for hexagonal groups)

        Returns: a Hermann-Mauguin style string for the site symmetry
        """
        if type(index) == int:
            pass
        elif type(index) == str:
            #Extract letter from number-letter combinations ("4d"->"d")
            for c in index:
                if c.isalpha():
                    letter = c
                    break
            index = index_from_letter(letter, self.wyckoffs)
        if molecular is False:
            ops = self.w_symm[index][0]
        if molecular is True:
            ops = self.w_symm_m[index][0]
        return ss_string_from_ops(ops, self.number, dim=self.dim)

    def get_wyckoff_symmetry_m(self, index):
        """
        Returns the site symmetry symbol for the Wyckoff position (with molecular=True)

        Args:
            index: the index of the Wyckoff position within the group
                The largest position is always 0

        Returns: a Hermann-Mauguin style string for the site symmetry
        """
        return self.get_wyckoff_symmetry(index, molecular=True)

    def __iter__(self):
        yield from self.Wyckoff_positions

    def __getitem__(self, index):
        return self.get_wyckoff_position(index)

    def __len__(self):
        return self.multiplicity

    def print_all(self):
        """
        Prints useful information about the Group.
        """
        try:
            print(self.string_long)
        except:
            if self.dim == 3:
                s = "-- Space "
            elif self.dim == 2:
                s = "-- Layer "
            elif self.dim == 1:
                s = "-- Rod "
            elif self.dim == 0:
                s = "-- Point group " + self.symbol + " --"
            if self.dim != 0:
                s += "group # "+str(self.number)+" --"
            for wp in self.Wyckoff_positions:
                s += "\n"+str(wp.multiplicity)+wp.letter+" site symm: "
                s += ss_string_from_ops(wp.symmetry_m[0], self.number, dim=self.dim)
                for op in wp.ops:
                    s += "\n  " + op.as_xyz_string()
            self.string_long = s
            print(self.string_long)

    def gen_pos(self):
        """
        Returns the general Wyckoff position
        """
        return self.Wyckoff_positions[0]

