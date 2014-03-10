#!/afs/rhic.bnl.gov/@sys/opt/astro/SL64/anaconda/bin
# yeti: /vega/astro/users/jl3509/tarball/anacondaa/bin/python
# Jia Liu 2014/3/7
# Overview: this code creates mass maps from simulation
################ steps #####################
#1) smoothing, use random galaxy direction, and w as wegith
#2) KSvw
#3) count peaks, MF, powerspectrum (this will be in a separate code)

import WLanalysis
from emcee.utils import MPIPool
import os
import numpy as np
from scipy import *
import scipy.ndimage as snd
import sys

########## define constants ############
ngal_arcmin = 5.0
zmax=1.3
zmin=0.2

ngal_cut = ngal_arcmin*(60**2*12)/512**2# = 0.82, cut = 5 / arcmin^2
PPR512=8468.416479647716#pixels per radians
PPA512=2.4633625
rad2pix=lambda x: around(512/2.0-0.5 + x*PPR512).astype(int) #from radians to pixel location
sigmaG_arr = (0.5, 1, 1.8, 3.5, 5.3, 8.9)

full_dir = '/direct/astro+astronfs01/workarea/jia/CFHT/full_subfields/'
KS_dir = '/direct/astro+astronfs03/workarea/jia/CFHT/KSsim/'
sim_dir = '/direct/astro+astronfs01/workarea/jia/CFHT/galaxy_catalogue_128R/'
fidu='mQ3-512b240_Om0.260_Ol0.740_w-1.000_ns0.960_si0.800'
hi_w='mQ3-512b240_Om0.260_Ol0.740_w-0.800_ns0.960_si0.800'
hi_s='mQ3-512b240_Om0.260_Ol0.740_w-1.000_ns0.960_si0.850'
hi_m='mQ3-512b240_Om0.290_Ol0.710_w-1.000_ns0.960_si0.800'

####### maps to process #########
i_arr=[1,2]
R_arr=arange(1,129)
cosmo_arr=(fidu,hi_m,hi_w,hi_s)

####### end: define constant ####

####### functions ###############
SIMfn= lambda i, cosmo, R: sim_dir+'%s/raytrace_subfield%i_WL-only_%s_4096xy_%04dr.fit'%(cosmo, i, cosmo, R)
KSfn = lambda i, cosmo, R, sigmaG, zg: KS_dir+'%s/SIM_KS_sigma%02d_subfield%i_%s_%s_%04dr.fit'%(cosmo, sigmaG*10, i, zg, cosmo,R)#i=subfield, cosmo, R=realization, sigmaG=smoothing, zg=zgroup=(pz, rz, rz2)

def rndrot (e1, e2, iseed=None):
	'''rotate galaxy with ellipticity (e1, e2), by a random angle. 
	generate random rotation while preserve galaxy size and shape info
	'''
	if iseed:
		random.seed(iseed)
	ells = e1+1j*e2
	ells_new = -ells*exp(-4j*pi*rand(len(e1)))
	return real(ells_new), imag(ells_new)

#### test
# a=rand(10)+rand(10)*1j
# b=rndrot(a)
# abs(a)==abs(b) #return True

zcut_idx = lambda i: WLanalysis.readFits(full_dir+'zcut_idx_subfield%i.fit'%(i))

def eobs_fun (g1, g2, k, e1, e2):
	'''van wearbeke 2013 eq 5-6, get unbiased estimator for shear.
	Input:
	g1, g2: shear
	k: convergence
	e1, e2: galaxy intrinsic ellipticity
	Output:
	e_obs1, e_obs2
	'''
	g = (g1+1j*g2)/(1-k)
	eint = e1+1j*e2
	eobs = (g+eint)/(1-g*eint)
	return real(eobs), imag(eobs)

def fileGen(i, R, cosmo):
	'''
	Input:
	i: subfield range from (1, 2..13)
	R: realization range from (1..128)
	cosmo: one of the 4 cosmos (fidu, hi_m, hi_w, hi_s)
	Return:
	3 Me1 = e1*w # 3 are for 3 redshift groups
	3 Me2 = e2*w
	Mw = w
	'''
	### these are from simulation
	Ms1_pz_fn  = KS_dir+'SIM_Ms/SIM_Ms1_pz_subfield%i_%s_%04dr.fit' %(i, cosmo, R)
	Ms2_pz_fn  = KS_dir+'SIM_Ms/SIM_Ms2_pz_subfield%i_%s_%04dr.fit' %(i, cosmo, R)
	Ms1_rz1_fn = KS_dir+'SIM_Ms/SIM_Ms1_rz1_subfield%i_%s_%04dr.fit'%(i, cosmo, R)
	Ms2_rz1_fn = KS_dir+'SIM_Ms/SIM_Ms2_rz1_subfield%i_%s_%04dr.fit'%(i, cosmo, R)
	Ms1_rz2_fn = KS_dir+'SIM_Ms/SIM_Ms1_rz2_subfield%i_%s_%04dr.fit'%(i, cosmo, R)
	Ms2_rz2_fn = KS_dir+'SIM_Ms/SIM_Ms2_rz2_subfield%i_%s_%04dr.fit'%(i, cosmo, R)
	Mw_fn = KS_dir+'SIM_Mw_subfield%i.fit'%(i) # same for all R

	Marr = (Mw_fn, Ms1_pz_fn, Ms2_pz_fn, Ms1_rz1_fn, Ms2_rz1_fn, Ms1_rz2_fn, Ms2_rz2_fn)
	print 'fileGen', i, str(R)+'r', cosmo
	if WLanalysis.TestComplete(Marr, rm = False):
		Mw = WLanalysis.readFits(Mw_fn)
		Ms1_pz  = WLanalysis.readFits(Ms1_pz_fn )
		Ms2_pz  = WLanalysis.readFits(Ms2_pz_fn )
		Ms1_rz1 = WLanalysis.readFits(Ms1_rz1_fn)
		Ms2_rz1 = WLanalysis.readFits(Ms2_rz1_fn)
		Ms1_rz2 = WLanalysis.readFits(Ms1_rz2_fn)
		Ms2_rz2 = WLanalysis.readFits(Ms2_rz2_fn)
		createfiles = 0
	
	elif WLanalysis.TestComplete((Mw_fn,),rm = False):
		#Mw = WLanalysis.readFits(Mw_fn)
		WLanalysis.TestComplete(Marr[1:], rm = True)
		createfiles = 1 #flag to create Ms's
	else:
		createfiles = 2 #flag to create everything

	if createfiles:
		idx = zcut_idx (i)
		y, x, e1, e2, w = (WLanalysis.readFits(full_dir+'yxew_zcut0213_subfield%i.fit'%(i))).T
	
		#idx = zcut_idx (i)#redshift cut
		#simfile = WLanalysis.readFits(SIMfn(i,cosmo,R))[idx, [0,1,2,4,5,6,8,9,10]]#simulation file at redshift cut
		#s1_pz, s2_pz, k_pz, s1_rz1, s2_rz1, k_rz1, s1_rz2, s2_rz2, k_rz2 = simfile.T
		
		k_pz, s1_pz, s2_pz, k_rz1, s1_rz1, s2_rz1, k_rz2, s1_rz2, s2_rz2 = (WLanalysis.readFits(SIMfn(i,cosmo,R))[idx].T)[[0,1,2,4,5,6,8,9,10]]
		
		eint1, eint2 = rndrot(e1, e2, iseed=R)#random rotation
			
		## get reduced shear
		e1_pz, e2_pz = eobs_fun(s1_pz, s2_pz, k_pz, eint1, eint2)
		e1_rz1, e2_rz1 = eobs_fun(s1_rz1, s2_rz1, k_rz1, eint1, eint2)
		e1_rz2, e2_rz2 = eobs_fun(s1_rz2, s2_rz2, k_rz2, eint1, eint2)
			
		kk = array([k_rz1, e1_pz*w, e2_pz*w, e1_rz1*w, e2_rz1*w, e1_rz2*w, e2_rz2*w, w])
		print 'coords2grid'
		Mk, Ms1_pz, Ms2_pz, Ms1_rz1, Ms2_rz1, Ms1_rz2, Ms2_rz2, Mw = WLanalysis.coords2grid(x, y, kk)[0]
		if createfiles == 2:
			WLanalysis.writeFits(Mw, Mw_fn)
		#Marr = (Mw_fn, Ms1_pz_fn, Ms2_pz_fn, Ms1_rz1_fn, Ms2_rz1_fn, Ms1_rz2_fn, Ms2_rz2_fn)
		j = 1
		for iM in (Ms1_pz, Ms2_pz, Ms1_rz1, Ms2_rz1, Ms1_rz2, Ms2_rz2):
			WLanalysis.writeFits(iM, Marr[j])
			j+=1
		### add Mk just for comparison ###
		Mk_fn = KS_dir+'SIM_Mk/SIM_Mk_rz1_subfield%i_%s_%04dr.fit'%(i, cosmo, R)
		WLanalysis.writeFits(Mk, Mk_fn)
		
	return Ms1_pz, Ms2_pz, Ms1_rz1, Ms2_rz1, Ms1_rz2, Ms2_rz2, Mw

### test, pass, still need to check actual map 
# Ms1_pz, Ms2_pz, Ms1_rz1, Ms2_rz1, Ms1_rz2, Ms2_rz2, Mw = fileGen(1, 1, fidu)

####### smooth and KS inversion #########
	
def KSmap(iiRcosmo):
	'''Input:
	i: subfield range from (1, 2..13)
	R: realization range from (1..128)
	cosmo: one of the 4 cosmos (fidu, hi_m, hi_w, hi_s)
	Return:
	KS inverted map
	'''
	i, R, cosmo = iiRcosmo
	Ms1_pz, Ms2_pz, Ms1_rz1, Ms2_rz1, Ms1_rz2, Ms2_rz2, Mw = fileGen(i, R, cosmo)
	Ms_arr = ((Ms1_pz, Ms2_pz), (Ms1_rz1, Ms2_rz1), (Ms1_rz2, Ms2_rz2))
	zgs=('pz', 'rz1', 'rz2')
	for sigmaG in sigmaG_arr:
		for j in range(3):
			print 'KSmap i, R, sigmaG, cosmo', i, R, sigmaG, cosmo
			KS_fn = KSfn(i, cosmo, R, sigmaG, zgs[j])
			Me1, Me2 = Ms_arr[j]
			
			if os.path.isfile(KS_fn):
				kmap = WLanalysis.readFits(KS_fn)
			else:
				Me1_smooth = WLanalysis.weighted_smooth(Me1, Mw, PPA=PPA512, sigmaG=sigmaG)
				Me2_smooth = WLanalysis.weighted_smooth(Me2, Mw, PPA=PPA512, sigmaG=sigmaG)
				kmap = WLanalysis.KSvw(Me1_smooth, Me2_smooth)
				WLanalysis.writeFits(kmap, KS_fn)

# test KSmap(1, 1, fidu), pass
def iRcosmo_fcn(i_arr, R_arr, cosmo_arr):
	'''Prepare list for mapping KSmap function.
	'''
	iRcosmo=[[1,1,''],]*(len(i_arr)*len(R_arr)*len(cosmo_arr))
	j=0
	for i in i_arr:
		for R in R_arr:
			for cosmo in cosmo_arr:
				iRcosmo[j]=[i,R,cosmo]
				j+=1
	return iRcosmo


iRcosmo = iRcosmo_fcn(i_arr, R_arr, cosmo_arr)

## Initialize the MPI pool
pool = MPIPool()
## Make sure the thread we're running on is the master
#if not pool.is_master():
	#pool.wait()
	#sys.exit(0)
## logger.debug("Running with MPI...")
pool.map(KSmap, iRcosmo)
	
savetxt(KS_dir+'done.ls','done')
sys.exit(0)