#!python
# Jia Liu 2014/09/12
# What the code does: create noiseless mass maps for fiducial cosmology, and calculate the power spectrum
# Cluster: XSEDE Stampede

import WLanalysis
from emcee.utils import MPIPool
import os
import numpy as np
from scipy import *
import scipy.ndimage as snd
import sys
sigmaG = 0.5
PPA512 = 2.4633625
KS_dir = '/scratch/02977/jialiu/KSsim/GoodOnly/noiseless/'
sim_dir = '/home1/02977/jialiu/cat/'
params = genfromtxt(KS_dir+'cosmo_params.txt')

kappaGen = lambda r: WLanalysis.readFits( sim_dir+'emu1-512b240_Om0.305_Ol0.695_w-0.879_ns0.960_si0.765/emulator_subfield9_WL-only_emu1-512b240_Om0.305_Ol0.695_w-0.879_ns0.960_si0.765_4096xy_%04dr.fit'%(r)).T[0]
#k, s1, s2

y, x = WLanalysis.readFits(KS_dir+'yxewm_subfield1_zcut0213.fit').T[:2]

def kmapPs (r):
	print i
	k = kappaGen(r)
	kmap, galn = WLanalysis.coords2grid(x, y, array([k, ]))
	kmap_smooth = WLanalysis.weighted_smooth(kmap, galn, PPA=PPA512, sigmaG=sigmaG)
	ps = WLanalysis.PowerSpectrum(kmap,sizedeg=12.0)[-1]
	return ps

pool = MPIPool()
ps_mat = pool.map(kmapPs, range(1,1001))
WLanalysis.writeFits(ps_mat,KS_dir+'ps_mat.fit')
print 'Done'