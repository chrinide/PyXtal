from pyxtal.molecular_crystal import molecular_crystal
from random import randint
from time import time 
from pymatgen.io.cif import CifWriter
import os

mols = ['CH4', 'H2O', 'NH3', 'urea', 'benzene', 'C60', 'pentacene', 'roy', 'aspirin']
filename = 'out.cif'
if os.path.isfile(filename):
    os.remove(filename)

for mol in mols:
    for i in range(10):
        run = True
        while run:
            sg = 19 #randint(4, 191)
            start = time()
            rand_crystal = molecular_crystal(sg, [mol], [4], 1.6)
            if rand_crystal.valid:
                run = False
                print('Mol: {0:s}  SG: {1:d} Time: {2:.3f} seconds'.format(mol, sg, time()-start))
                content = str(CifWriter(rand_crystal.struct, symprec=0.1))
                with open(filename, 'a+') as f:
                    f.writelines(content)
