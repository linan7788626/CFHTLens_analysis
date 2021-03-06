##########################################################
### This code is for Jia's project B - try to find
### observational evidence of over density at peak location
### as discovered by Yang 2011.
### It does the following:
### 1) find PDF for # gal within 2 arcmin as fcn of peak
### hights
### 2) the same, as 1) but for random direction
### 3) L-M conversion: L_k -> halo mass, using Vale&JPO06 (2014/12)
### 4) kappa_proj assuming NFW (2014/12)

import numpy as np
from scipy import *
from pylab import *
import os
import WLanalysis
from scipy import interpolate,stats
from scipy.integrate import quad
import scipy.optimize as op
import sys

######## for stampede #####
from emcee.utils import MPIPool
obsPK_dir = '/home1/02977/jialiu/obsPK/'

######## for laptop #####
#obsPK_dir = '/Users/jia/CFHTLenS/obsPK/'
#plot_dir = obsPK_dir+'plot/'

make_kappa_predict = 1

########### constants ######################
z_lo = 0.6
z_hi = '%s_hi'%(z_lo)

sizes = (1330, 800, 1120, 950)
centers = array([[34.5, -7.5], [134.5, -3.25],[214.5, 54.5],[ 332.75, 1.9]])
PPR512=8468.416479647716
PPA512=2.4633625
c = 299792.458#km/s
Gnewton = 6.674e-8#cgs cm^3/g/s
H0 = 70.0
h = 0.7
OmegaM = 0.25#0.3
OmegaV = 1.0-OmegaM
rho_c0 = 9.9e-30#g/cm^3
M_sun = 1.989e33#gram

############################################
############ functions #####################
############################################

########### generate maps ##################

maskGen = lambda Wx, zcut, sigmaG: load(obsPK_dir+'maps/Mask_W%s_%s_sigmaG%02d.npy'%(Wx,zcut,sigmaG*10))

kmapGen = lambda Wx, zcut, sigmaG: WLanalysis.readFits('/Users/jia/CFHTLenS/obsPK/maps/W%i_KS_%s_hi_sigmaG%02d.fit'%(Wx,zcut,sigmaG*10))*maskGen(Wx, zcut, sigmaG)


bmodeGen = lambda Wx, zcut, sigmaG: WLanalysis.readFits('/Users/jia/CFHTLenS/obsPK/maps/W%i_Bmode_%s_sigmaG%02d.fit'%(Wx, zcut, sigmaG))*maskGen(Wx, zcut, sigmaG)

cat_gen = lambda Wx: np.load(obsPK_dir+'W%s_cat_z0213_ra_dec_redshift_weight_MAGi_Mvir_Rvir_DL.npy'%(Wx))
#columns: ra, dec, redshift, weight, i, Mhalo, Rvir, DL
	

########## cosmologies #######################
# growth factor
H_inv = lambda z: 1.0/(H0*sqrt(OmegaM*(1+z)**3+OmegaV))
# luminosity distance Mpc
DL = lambda z: (1+z)*c*quad(H_inv, 0, z)[0]
# use interpolation instead of actual calculation, so we can operate on an array
z_arr = linspace(0.1, 1.4, 1000)
DL_arr = array([DL(z) for z in z_arr])
DL_interp = interpolate.interp1d(z_arr, DL_arr)
# find the rest magnitude at the galaxy, from observed magnitude cut
M_rest_fcn = lambda M_obs, z: M_obs - 5.0*log10(DL_interp(z)) - 25.0


##################### MAG_z to M100 ##########
datagrid_VO = np.load(obsPK_dir+'Mhalo_interpolator_VO.npy')#Mag_z, r-z, M100, residual
Minterp = interpolate.CloughTocher2DInterpolator(datagrid_VO[:,:2],datagrid_VO[:,2])
#usage: Minterp(MAGz_arr, r-z_arr)


def PeakPos (Wx, z_lo=0.6, z_hi='0.6_lo',noise=False, Bmode=False):
	'''For a map(kappa or bmode), find peaks, and its(RA, DEC)
	return 3 columns: [kappa, RA, DEC]
	'''
	#print 'noise', noise, Wx
	if Bmode:
		kmap = bmodeGen(Wx, z=z_hi)
	else:
		kmap = kmapGen(Wx, z=z_hi)
	ipeak_mat = WLanalysis.peaks_mat(kmap)
	imask = maskGen (Wx, z=z_lo)
	ipeak_mat[where(imask==0)]=nan #get ipeak_mat, masked region = nan
	if noise: #find the index for peaks in noise map
		idx_all = where((imask==1)&isnan(ipeak_mat))
		sample = randint(0,len(idx_all[0])-1,sum(~isnan(ipeak_mat)))
		idx = array([idx_all[0][sample],idx_all[1][sample]])
	else:#find the index for peaks in kappa map
		idx = where(~isnan(ipeak_mat)==True)
	kappaPos_arr = zeros(shape=(len(idx[0]),3))#prepare array for output
	for i in range(len(idx[0])):
		x, y = idx[0][i], idx[1][i]#x, y
		kappaPos_arr[i,0] = kmap[x, y]
		x = int(x-sizes[Wx-1]/2)+1
		y = int(y-sizes[Wx-1]/2)+1
		x /= PPR512# convert from pixel to radians
		y /= PPR512
		kappaPos_arr[i,1:] = WLanalysis.gnom_inv((y, x), centers[Wx-1])
	return kappaPos_arr.T

	

################## kappa projection 2014/12/14 ##############
rho_cz = lambda z: rho_c0*(OmegaM*(1+z)**3+(1-OmegaM))#critical density
Rvir_fcn = lambda M, z: (M*M_sun/(4.0/3.0*pi*200*rho_cz(z)))**0.3333
rad2arcmin = lambda distance: degrees(distance)*60.0


def Gx_fcn (x, cNFW=5.0):
	if x < 1:
		out = 1.0/(x**2-1.0)*sqrt(cNFW**2-x**2)/(cNFW+1.0)+1.0/(1.0-x**2)**1.5*arccosh((x**2+cNFW)/x/(cNFW+1.0))
	elif x == 1:
		out = sqrt(cNFW**2-1.0)/(cNFW+1.0)**2*(cNFW+2.0)/3.0
	elif 1 < x <= cNFW:
		out = 1.0/(x**2-1.0)*sqrt(cNFW**2-x**2)/(cNFW+1.0)-1.0/(x**2-1.0)**1.5*arccos((x**2+cNFW)/x/(cNFW+1.0))
	elif x > cNFW:
		out = 0
	return out

f = 1.043
def kappa_proj (Mvir, Rvir, z_fore, x_fore, y_fore, DL_fore, z_back, x_back, y_back, DL_back, cNFW=5.0):
	'''return a function, for certain foreground halo, 
	calculate the projected mass between a foreground halo and a background galaxy pair.
	'''
	#f = 1.043#=1.0/(log(1+cNFW)-cNFW/(1+cNFW)) with cNFW=5.0
	two_rhos_rs = Mvir*M_sun*f*cNFW**2/(2*pi*Rvir**2)#cgs, see LK2014 footnote
	Dl = DL_fore/(1+z_fore)**2
	Dl_cm = 3.08567758e24*Dl # D_angular = D_luminosity/(1+z)**2
	theta_vir = Rvir/Dl_cm	
	Ds = DL_back/(1+z_back)**2
	Dls = Ds - Dl
	DDs = Ds/(Dl*Dls)/3.08567758e24# 3e24 = 1Mpc/1cm
	SIGMAc = 1.07e+27*DDs#(c*1e5)**2/4.0/pi/Gnewton=1.0716311756473212e+27
	#x_rad, y_rad = xy_fcn(array([ra_back, dec_back]))
	theta = sqrt((x_fore-x_back)**2+(y_fore-y_back)**2)
	x = cNFW*theta/theta_vir
	Gx = Gx_fcn(x, cNFW)
	kappa_p = two_rhos_rs/SIGMAc*Gx
	return kappa_p

if make_kappa_predict:
	from scipy.spatial import cKDTree
	zcut = 0.2#0.6
	r = 0.0019#0.002rad = 7arcmin, within which I search for contributing halos

	Wx = int(sys.argv[1])
	center = centers[Wx-1]
	icat = cat_gen(Wx).T

	ra, dec, redshift, weight, MAGi, Mhalo, Rvir, DL = icat
	Mhalo[Mhalo>2e15] = 2e15#prevent halos to get crazy mass
	f_Wx = WLanalysis.gnom_fun(center)
	xy = array(f_Wx(icat[:2])).T

	idx_back = where(redshift>zcut)[0]
	xy_back = xy[idx_back]

	kdt = cKDTree(xy)
#nearestneighbors = kdt.query_ball_point(xy_back[:100], 0.002)
	def kappa_individual_gal (i):
		'''for individual background galaxies, find foreground galaxies within 7 arcmin and sum up the kappa contribution
		'''
		print i
		iidx_fore = array(kdt.query_ball_point(xy_back[i], r))	
		x_back, y_back = xy_back[i]
		z_back, DL_back = redshift[idx_back][i], DL[idx_back][i]
		ikappa = 0
		for jj in iidx_fore:
			x_fore, y_fore = xy[jj]
			jMvir, jRvir, z_fore, DL_fore = Mhalo[jj], Rvir[jj], redshift[jj], DL[jj]
			if z_fore >= z_back:
				kappa_temp = 0
			else:
				kappa_temp = kappa_proj (jMvir, jRvir, z_fore, x_fore, y_fore, DL_fore, z_back, x_back, y_back, DL_back, cNFW=5.0)
				if isnan(kappa_temp):
					kappa_temp = 0
			ikappa += kappa_temp
			
			if kappa_temp>0:
				theta = sqrt((x_fore-x_back)**2+(y_fore-y_back)**2)
				print '%s\t%.2f\t%.3f\t%.3f\t%.4f\t%.6f'%(jj,log10(jMvir), z_fore, z_back, rad2arcmin(theta), kappa_temp)	
		return ikappa

	#a=map(kappa_individual_gal, randint(0,len(idx_back)-1,5))
	step=1e4
	def temp (ix):
		print ix
		kappa_all = map(kappa_individual_gal, arange(ix, amin([len(idx_back), ix+step])))
		np.save(obsPK_dir+'temp/kappa_proj%i_%07d.npy'%(Wx, ix),kappa_all)
	pool = MPIPool()
	ix_arr = arange(0, len(idx_back), step)
	pool.map(temp, ix_arr)
#for Wx in (1,):#range(1,5):
	#sizes = (1330, 800, 1120, 950)
	#print Wx
	#isize = sizes[Wx-1]
	#center = centers[Wx-1]
	#icat = cat_gen(Wx).T
	##ra, dec, redshift, weight, MAGi, Mhalo, Rvir, DL = icat
	#f_Wx = WLanalysis.gnom_fun(center)
	
	#y, x = array(f_Wx(icat[:2]))
	#weight = icat[3]
	#k = np.load(obsPK_dir+'kappa_predict_W%i.npy'%(Wx))
	
	#A, galn = WLanalysis.coords2grid(x, y, array([k*weight, weight]), size=isize)
	#Mkw, Mw = A

	#mat_dir = '/Users/jia/CFHTLenS/catalogue/Me_Mw_galn/'
	#Mkw = np.load(mat_dir+'W%i_Mkw_pred.npy'%(Wx))
	#Mw = np.load(mat_dir+'W%i_Mw_pred.npy'%(Wx))
	#for sigmaG in (5.3, 8.9):
		#print Wx, sigmaG
		########## masks
		#galn = WLanalysis.readFits(obsPK_dir+'maps/W%s_galn_1.3_lo_sigmaG%02d.fit'%(Wx,sigmaG*10))
		#mask = ones(shape=galn.shape)
		#idx = where(galn<0.5)
		#mask[idx] = 0
		#mask_smooth = WLanalysis.smooth(mask, 0)
		
		#kmap_lensing = WLanalysis.readFits(obsPK_dir+'maps/W%i_KS_1.3_lo_sigmaG%02d.fit'%(Wx, sigmaG*10))
		#kmap_predict = WLanalysis.weighted_smooth(Mkw*mask_smooth, Mw*mask_smooth, PPA=PPA512, sigmaG=sigmaG)
		##np.save(obsPK_dir+'kmap_W%i_lensing_sigmaG%02d'%(Wx, sigmaG), kmap_lensing)
		#np.save(obsPK_dir+'maps/kmap_W%i_predict_sigmaG%02d'%(Wx, sigmaG*10), kmap_predict)
		
		#figure(figsize=(8,4))
		#subplot(121)
		#imshow(kmap_lensing, vmax=3*std(kmap_lensing), vmin=-2*std(kmap_lensing), origin = 'lower')
		#title('W%i kmap_lensing'%(Wx))
		#colorbar()
		#subplot(122)
		#imshow(kmap_predict-mean(kmap_predict), vmax=3*std(kmap_predict), vmin=-2*std(kmap_lensing), origin = 'lower')
		#title('W%i kmap_predict'%(Wx))
		#colorbar()
		#savefig(plot_dir+'kmap_W%i_lensing_predict_sigmaG%s.jpg'%(Wx,sigmaG))
		#close()
print 'done-done-done'