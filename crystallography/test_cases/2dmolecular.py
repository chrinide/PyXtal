if __name__ == "__main__":
    #-------------------------------- Options -------------------------
    from os import mkdir
    from crystallography.molecular_crystal import *

    parser = OptionParser()
    parser.add_option("-s", "--number", dest="num", metavar='num', default=36, type=int,
            help="desired space group number: 1-230, e.g., 36")
    parser.add_option("-e", "--molecule", dest="molecule", default='H2O', 
            help="desired molecules: e.g., H2O", metavar="molecule")
    parser.add_option("-n", "--numMols", dest="numMols", default=4, 
            help="desired numbers of molecules: 4", metavar="numMols")
    parser.add_option("-t", "--thickness", dest="thickness", default=4.0, type=float, 
            help="volume factor: default 4.0", metavar="thickness")
    parser.add_option("-f", "--factor", dest="factor", default=2.0, type=float, 
            help="volume factor: default 2.0", metavar="factor")
    parser.add_option("-v", "--verbosity", dest="verbosity", default=0, type=int, help="verbosity: default 0; higher values print more information", metavar="verbosity")
    parser.add_option("-a", "--attempts", dest="attempts", default=1, type=int, 
            help="number of crystals to generate: default 1", metavar="attempts")
    parser.add_option("-o", "--outdir", dest="outdir", default="out", type=str, 
            help="Directory for storing output cif files: default 'out'", metavar="outdir")
    parser.add_option("-c", "--checkatoms", dest="checkatoms", default="True", type=str, 
            help="Whether to check inter-atomic distances at each step: default True", metavar="outdir")
    parser.add_option("-i", "--allowinversion", dest="allowinversion", default="False", type=str, 
            help="Whether to allow inversion of chiral molecules: default False", metavar="outdir")

    (options, args) = parser.parse_args()    
    molecule = options.molecule
    number = options.numMols
    verbosity = options.verbosity
    attempts = options.attempts
    outdir = options.outdir
    if options.checkatoms == "True" or options.checkatoms == "False":
        checkatoms = eval(options.checkatoms)
    else:
        print("Invalid value for -c (--checkatoms): must be 'True' or 'False'.")
        checkatoms = True
    if options.allowinversion == "True" or options.allowinversion == "False":
        allowinversion = eval(options.allowinversion)
    else:
        print("Invalid value for -i (--allowinversion): must be 'True' or 'False'.")
        allowinversion = False
    
    numMols = []
    if molecule.find(',') > 0:
        strings = molecule.split(',')
        system = []
        for mol in strings:
            system.append(get_ase_mol(mol))
        for x in number.split(','):
            numMols.append(int(x))
    else:
        system = [get_ase_mol(molecule)]
        numMols = [int(number)]
    orientations = None

    #Layergroup numbers to test
    numrange = list(range(1, 81))

    for num in numrange:
        for i in range(attempts):
            print('---------------Layergroup '+str(num)+'---------------')
            start = time()
            numMols0 = np.array(numMols)
            rand_crystal = molecular_crystal_2D(num, system, numMols0, options.thickness, options.factor, orientations=orientations, check_atomic_distances=checkatoms, allow_inversion=allowinversion)
            end = time()
            timespent = np.around((end - start), decimals=2)
            if rand_crystal.valid:
                '''written = False
                try:
                    mkdir(outdir)
                except: pass
                try:
                    comp = str(rand_crystal.struct.composition)
                    comp = comp.replace(" ", "")
                    cifpath = outdir + '/' + comp + "_" + str(i+1) + '.cif'
                    CifWriter(rand_crystal.struct, symprec=0.1).write_file(filename = cifpath)
                    written = True
                except: pass'''

                #spglib style structure called cell
                ans = get_symmetry_dataset(rand_crystal.spg_struct, symprec=1e-1)
                sg = Layergroup(num).sgnumber
                if ans is not None:
                    print('Space group requested: '+str(sg)+' generated', ans['number'], 'vol: ', rand_crystal.volume)
                else:
                    print('Space group requested: '+str(sg)+' Could not calculate generated.***********')
                '''if written is True:
                    print("    Output to "+cifpath)
                else:
                    print("    Could not write cif file.")'''

                #Print additional information about the structure
                if verbosity > 0:
                    print("Time required for generation: " + str(timespent) + "s")
                    print("Molecular Wyckoff positions:")
                    for ms in rand_crystal.mol_generators:
                        print(str(ms.mol.composition) + ": " + str(ms.multiplicity)+str(ms.letter)+" "+str(ms.position))
                if verbosity > 1:
                    print(rand_crystal.struct)

            #If generation fails
            else: 
                print('something is wrong')
                print('Time spent during generation attempt: ' + str(timespent) + "s")
