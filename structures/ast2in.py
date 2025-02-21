import os
from shutil import copyfile
from os.path import join as pjoin
from os import scandir
from sys import argv

import safir_tools as st
import numpy as np
import csv

'''FDS results handling - Adiabatic Surface Temperature devices'''


class AST:
    def __init__(self, fdsfile, calc_dir):
        self.calc_dir = calc_dir
        with open(f'{fdsfile}') as f:
            self.fdsfile = f.readlines()

        for line in self.fdsfile:
            if '&HEAD' in line:
                for s in line.split():
                    if 'CHID' in s:
                        chid = s.split('=')[-1][1:-2]
                        break

        with open(f'{chid}_devc.csv') as f:
            self.csvfile = [i for i in csv.reader(f)][1:]
            
        self.locations = self.get_locs()
        
    def find_devcs(self):
        devc = []
        for l in self.fdsfile:
            if '&DEVC' in l:
                devc.append(l.split())

        return devc

    def find_locations(self, devcs):
        locations = {}
        id = None
        xyz = None

        for d in devcs:
            save = True
            for param in d:
                if param.startswith('ID='):
                    id = param.split("'")[1]
                elif 'XYZ' in param:
                    xyz = [float(c) for c in param[4:-1].split(",")]
                elif 'QUANTITY' in param:
                    if not param.split('=')[1].startswith("'ADIAB"):
                        save = False
            if save:
                try:
                    locations[id] = xyz
                except:
                    exit(2)

        return locations

    def write_csv(self, data):
        with open('locations.csv', 'w') as file:
            file.write(','.join(data.keys()) + '\n')
            for i in range(3):
                file.write(','.join([j[i] for j in data.values()]) + '\n')

        return 0

    # find locations of AST devices
    def get_locs(self):
        dvc = self.find_devcs()
        locations = self.find_locations(dvc)  # {id:[x,y,z]...}

        return locations

    # prepare SAFIR function files from AST device records
    def csv2safir(self):
        def produce_txt(name, table):
            with open(pjoin(self.calc_dir, f'{name}.txt'), 'w') as file:
                file.write('\n'.join(['\t'.join(t) for t in table]))

        time = [i[0] for i in self.csvfile[1:]]
        labels = self.csvfile[0][1:]
        data = self.csvfile[1:]

        tables = {}
        for e, i in enumerate(labels):
            tables[i] = list(zip(time, [data[j][e + 1] for j in range(len(time))]))

        for n, t in tables.items():
            produce_txt(n, t)


# import InFile
class Calculate4AST:
    def __init__(self, inpath, fdspath, calc_dir='calc_files', config_dir='./config'):
        # set paths
        self.calc_dir = pjoin('.', calc_dir)
        try:
            os.mkdir(self.calc_dir)
        except OSError:
            print(f'{self.calc_dir} already exists')
        self.config_path = config_dir

        # import data
        self.infile = st.read_in(inpath)
        self.middles = self.find_middles()
        self.truss_middles = self.find_middles(enttype='t')
        self.asts = AST(fdspath, self.calc_dir)

        # create attributes
        self.newbeams = []
        self.newtrusses = []
        self.newbeamtypes = self.infile.beamtypes.copy()
        self.newtrusstypes = self.infile.trusstypes.copy()

    # find middle node of beams
    def find_middles(self, enttype='b'):
        mids = []
        if enttype == 'b':
            for b in self.infile.beams:
                mids.append(self.infile.nodes[b[2] - 1][1:])    # middle node tag of the BEAM element is b[2]
        elif enttype == 't':
            for t in self.infile.trusses:
                truss_points = [np.array(self.infile.nodes[t[i]-1][1:]) for i in [0, 1]]
                mids.append(truss_points[0] + (truss_points[1] - truss_points[0])/2)

        else:
            raise ValueError('Invalid "enttype" in find_middles function')

        return mids  # [[x1, y2, z2], ... [xn, yn, zn]]

    # find the nearest AST device to the point
    def find_ast(self, point):
        def what_dist(p1, p2):
            return np.linalg.norm(np.array(p1) - np.array(p2))

        asttag = ''
        min_dist = 1e9
        all_asts = self.asts.locations

        for ak, av in all_asts.items():
            actual_dist = what_dist(point, av)
            if actual_dist < min_dist:
                min_dist = actual_dist
                asttag = ak

        return asttag

    # assign btypes to proper beams
    def assign2beams(self):
        for i, b in enumerate(self.infile.beams):
            newbtype = [f'{self.infile.beamtypes[b[-1] - 1][0][:-4]}_{self.find_ast(self.middles[i])}.tem',
                        self.infile.beamtypes[b[-1] - 1][1]]
            try:
                newbtypeindex = self.newbeamtypes.index(newbtype)
            except ValueError:
                self.newbeamtypes.append(newbtype)
                newbtypeindex = len(self.newbeamtypes) - 1

            self.newbeams.append(b[:-1] + [newbtypeindex+1])

        return 0

    # assign temp_curves to proper trusses
    def assign2trusses(self):
        for i, t in enumerate(self.infile.trusses):
            newttype = [f'{self.find_ast(self.truss_middles[i])}.txt',
                        *self.infile.trusstypes[t[-1]-1][1:]]
            try:
                newttypeindex = self.newtrusstypes.index(newttype)
            except ValueError:
                self.newtrusstypes.append(newttype)
                newttypeindex = len(self.newtrusstypes)-1

            self.newtrusses.append(t[:-1] + [newttypeindex+1])

        return 0

    # save fdsfile
    def write_modified_in(self):
        def to_str(item):
            if type(item) == list:
                return [str(i) for i in item]
            return str(item)

        newinfilelines = []

        # === wrt ===
        # -2    don't edit
        # -1    save beamtypes number in the next line
        # 0     save newbeamtypes
        # 0.5   save newtrussetypes
        # 1     save newbeams
        # 1.5   save newtrusses
        wrt = -2
        for line in self.infile.file_lines:
            # save new beam number
            if 'ELEMENTS' in line:
                wrt = -1
                newinfilelines.append(line)

            elif wrt == -1:
                newinfilelines.append('\t'+'\t'.join(line.split()[:-1]+[str(len(self.newbeamtypes))])+'\n')
                wrt = -2

            elif line.startswith('     TRUSS'):
                newinfilelines.append('\t'.join(line.split()[:-1]+[str(len(self.newtrusstypes))])+'\n')

            # write new beams an beamtypes
            elif 'NODOFBEAM' in line:
                newinfilelines.append(line)     # add current line
                wrt = 0

            elif wrt == -2:
                newinfilelines.append(line)     # add current line

            elif wrt == 0 and 'ELEM' in line:
                # add new beamtypes
                for b in self.newbeamtypes:
                    translation = '\n'.join([f'TRANSLATE  {to_str(i+1)}  {to_str(t)}' for i, t in enumerate(b[1])])
                    newinfilelines.append(f'{b[0]}\n{translation}\nEND_TRANS\n')
                wrt = 1

            elif wrt == 0:
                continue    # pass old beamtypes

            elif wrt == 1:
                if 'ELEM' not in line:
                    [newinfilelines.append(f'\t\tELEM\t{"    ".join(to_str(b))}\n') for b in self.newbeams]   # add all new beams

                    if 'NODOFTRUSS' in line:    # switch to trusses
                        newinfilelines.append(line)
                        wrt = 0.5
                    else:
                        wrt = -2    # stop passing routine
                else:
                    continue  # pass old beam definitions

            # write new trusses an trusstypes
            elif 'NODOFTRUSS' in line:
                newinfilelines.append(line)
                wrt = 0.5

            elif wrt == -2:
                newinfilelines.append(line)     # add current line

            elif wrt == 0.5 and 'ELEM' in line:
                # add new trusstypes
                for t in self.newtrusstypes:
                    newinfilelines.append('\t'.join(to_str(t) + ['\n']))
                wrt = 1.5

            elif wrt == 0:
                continue    # pass old trusstypes

            elif wrt == 1.5:
                if any(['ELEM' not in line, 'RELAX_ELEM' in line]):
                    [newinfilelines.append(f'\t\tELEM\t{"    ".join(to_str(t))}\n') for t in self.newtrusses]   # add all new trusses
                    newinfilelines.append(line)
                    wrt = -2    # stop passing routine
                else:
                    continue  # pass old truss definitions

        with open(pjoin(self.calc_dir, f'{self.infile.chid}_ast.in'),'w') as f:
            f.writelines(newinfilelines)

        return 0

    def edit_in(self):
        self.assign2beams()
        self.assign2trusses()
        self.write_modified_in()

        return 0

    def prepare_t2ds(self):
        for prof in self.newbeamtypes:
            astname = prof[0].split("_")[-1][:-4]
            try:
                with open(pjoin(self.config_path, f'{"_".join(prof[0].split("_")[:-1])}.in')) as f:
                    infile = f.readlines()

                # change thermal attack functions imposed on nodes
                for i, line in enumerate(infile):
                    if 'curvename' in line:
                        infile[i] = f'{astname}.txt'.join(line.split('curvename'))

                    # change convective heat transfer coefficient of steel to 35 in natural fire mode according to EN1991-1-2
                    elif 'STEEL' in line:
                        infile[i+1] = "35".join(infile[i + 1].split("25"))

                with open(pjoin(self.calc_dir, f'{prof[0][:-4]}.in'), 'w') as f:
                    f.writelines(infile)

                # copy torsional stiffness results
                copyfile(pjoin(self.config_path, f'{"_".join(prof[0].split("_")[:-1])}-t.TOR'),
                               pjoin(self.calc_dir, f'{prof[0][:-4]}-t.TOR'))

            except FileNotFoundError as error:
                #print(f'{"".join(prof[0].split("_")[:-1])}.in')
                copyfile(pjoin(self.config_path, f'{prof[0][:-4]}.in'),
                         pjoin(self.calc_dir, f'{prof[0][:-4]}.in'))

                copyfile(pjoin(self.config_path, f'{prof[0][:-4]}-t.TOR'),
                         pjoin(self.calc_dir, f'{prof[0][:-4]}-t.TOR'))

    def run_t2d(self, safir_path):
        self.asts.csv2safir()
        self.prepare_t2ds()

        for i in scandir(self.calc_dir):
            try:
                chid, ext = i.name.split('.')
            except ValueError:
                spltd = i.name.split('.')
                chid = '.'.join(spltd[:-1])
                ext = spltd[-1]

            if ext.lower() == 'in' and f'{chid}.tem' in [nbt[0] for nbt in self.newbeamtypes]:
                st.run_safir(i.path, safir_exe_path=safir_path, fix_rlx=False)


def move(infile_path, vector):
    newinfile = []
    with open(infile_path) as f:
        infile = f.readlines()

    for line in infile:
        spltd = line.split()

        try:
            if spltd[0] == 'NODE':
                xyz = np.array([float(c) for c in spltd[2:]])
                newinfile.append(f'\tNODE\t{spltd[1]}\t{"    ".join([str(j) for j in xyz+np.array(vector)])}\n')
            else:
                newinfile.append(line)
        except IndexError:
            newinfile.append(line)

    with open(f'{infile_path}_moved', 'w') as f:
        f.writelines(newinfile)

    print(f'file {infile_path} moved with {vector} vector')

    return 0


if __name__ == '__main__':
    # argv = [..., 'SAFIR mechanical input file path', 'FDS input file']
    a = Calculate4AST(*argv[1:])
    a.edit_in()
    a.run_t2d('D:/safir.exe')
    a.prepare_t2ds()
