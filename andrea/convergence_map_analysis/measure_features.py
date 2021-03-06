from __future__ import print_function,division,with_statement

import os,sys
import argparse,ConfigParser
import logging
import StringIO

######################################################################
##################LensTools functionality#############################
######################################################################

from lenstools import ConvergenceMap,Mask
from lenstools.simulations import CFHTemu1,CFHTcov
from lenstools.observations import CFHTLens
from lenstools.index import Indexer,PowerSpectrum,PDF,Peaks,MinkowskiAll,Moments
from lenstools import Ensemble

########################################################################
##################Other functionality###################################
########################################################################

from mpi4py import MPI
import numpy as np
from astropy.io import fits
from astropy.units import deg
from emcee.utils import MPIPool

import progressbar

###########################################################################
#############Read INI options file and write summary information###########
###########################################################################

def write_info(options):

	s = StringIO.StringIO()

	s.write("""
Realizations to analyze: 1 to {0}

###########################################

""".format(options.get("analysis","num_realizations")))

	s.write("""Implemented descriptors
-------------------

""")

	if options.has_section("power_spectrum"):
		s.write("""Power spectrum: {0} bins between l={1} and l={2}\n\n""".format(options.get("power_spectrum","num_bins"),options.get("power_spectrum","lmin"),options.get("power_spectrum","lmax")))

	if options.has_section("moments"):
		s.write("""The set of 9 moments\n\n""")

	if options.has_section("peaks"):
		s.write("""Peak counts: {0} bins between kappa={1} and kappa={2}\n\n""".format(options.get("peaks","num_bins"),options.get("peaks","th_min"),options.get("peaks","th_max")))

	if options.has_section("minkowski_functionals"):
		s.write("""Minkowski functionals: {0} bins between kappa={1} and kappa={2}\n\n""".format(options.get("minkowski_functionals","num_bins"),options.get("minkowski_functionals","th_min"),options.get("minkowski_functionals","th_max")))

	s.seek(0)
	return s.read()

##########################################################################################################################
##################FITS loader for the maps, must set angle explicitely since it's not contained in the header#############
##########################################################################################################################

def cfht_fits_loader(filename):

	kappa_file = fits.open(filename)
	angle = 3.4641016151377544*deg

	kappa = kappa_file[0].data.astype(np.float)

	kappa_file.close()

	return angle,kappa

###########################################################################
########################CFHT convergence maps measurer#####################
###########################################################################

def cfht_convergence_measure_all(filename,index,mask_filename,mean_subtract=False):

	"""
	Measures all the statistical descriptors of a convergence map as indicated by the index instance
	
	"""

	logging.debug("Processing {0}".format(filename))

	#Load the map
	conv_map = ConvergenceMap.load(filename,format=cfht_fits_loader)

	if mask_filename is not None:
		
		#Load the mask
		mask_profile = ConvergenceMap.load(mask_filename,format=cfht_fits_loader)
		logging.debug("Loading mask from {0}".format(mask_filename))
		#Mask the map
		masked_conv_map = conv_map.mask(mask_profile)

	if mean_subtract:
		
		if mask_filename is not None:
			masked_conv_map.data -= masked_conv_map.mean()
		else:
			conv_map.data -= conv_map.mean()

	#Allocate memory for observables
	descriptors = index
	observables = np.zeros(descriptors.size)

	#Measure descriptors as directed by input
	for n in range(descriptors.num_descriptors):

		
		if type(descriptors[n]) == PowerSpectrum:
			
			if mask_filename is None:
				l,observables[descriptors[n].first:descriptors[n].last] = conv_map.powerSpectrum(descriptors[n].l_edges)
			else:
				l,observables[descriptors[n].first:descriptors[n].last] = (conv_map*mask_profile).powerSpectrum(descriptors[n].l_edges)

		elif type(descriptors[n]) == Moments:

			if mask_filename is None:
				observables[descriptors[n].first:descriptors[n].last] = conv_map.moments(connected=descriptors[n].connected)
			else:
				observables[descriptors[n].first:descriptors[n].last] = masked_conv_map.moments(connected=descriptors[n].connected)
		
		elif type(descriptors[n]) == Peaks:
			
			if mask_filename is None:
				v,observables[descriptors[n].first:descriptors[n].last] = conv_map.peakCount(descriptors[n].thresholds,norm=descriptors[n].norm)
			else:
				v,observables[descriptors[n].first:descriptors[n].last] = masked_conv_map.peakCount(descriptors[n].thresholds,norm=descriptors[n].norm)

		elif type(descriptors[n]) == PDF:

			if mask_filename is None:
				v,observables[descriptors[n].first:descriptors[n].last] = conv_map.pdf(descriptors[n].thresholds,norm=descriptors[n].norm)
			else:
				v,observables[descriptors[n].first:descriptors[n].last] = masked_conv_map.pdf(descriptors[n].thresholds,norm=descriptors[n].norm)
		
		elif type(descriptors[n]) == MinkowskiAll:
			
			if mask_filename is None:
				v,V0,V1,V2 = conv_map.minkowskiFunctionals(descriptors[n].thresholds,norm=descriptors[n].norm)
			else:
				v,V0,V1,V2 = masked_conv_map.minkowskiFunctionals(descriptors[n].thresholds,norm=descriptors[n].norm)
			
			observables[descriptors[n].first:descriptors[n].last] = np.hstack((V0,V1,V2))
		
		elif type(descriptors[n]) == MinkowskiSingle:
			
			raise ValueError("Due to computational performance you have to measure all Minkowski functionals at once!")
		
		else:
			
			raise ValueError("Measurement of this descriptor not implemented!!!")

	#Return
	return observables

######################################################################################
##########Measurement object, handles the feature measurements from the maps##########
######################################################################################

class Measurement(object):

	"""
	Class handler for the maps feature measurements
	
	"""

	def __init__(self,model,options,subfield,smoothing_scale,measurer,**kwargs):

		self.model = model
		self.options = options
		self.subfield = subfield
		self.smoothing_scale = smoothing_scale
		self.measurer = measurer
		self.kwargs = kwargs

		#Build elements of save path for the features
		self.save_path = options.get("analysis","save_path")
		
		try:
			self.cosmo_id = self.model._cosmo_id_string
		except:
			pass

		self.subfield_name = "subfield{0}".format(self.subfield)
		self.smoothing_name = "sigma{0:02d}".format(int(self.smoothing_scale * 10))

		if options.getboolean("analysis","mask"):
			self.kwargs["mask_filename"] = os.path.join(options.get("analysis","mask_directory"),options.get("analysis","mask_prefix")+"_sigma{0:02d}_subfield{1:02d}.fits".format(int(self.smoothing_scale * 10),self.subfield))
		else:
			self.kwargs["mask_filename"] = None

	@property
	def maskedFraction(self):

		if "mask_filename" in self.kwargs.keys():
			mask_profile = Mask.load(self.kwargs["mask_filename"],format=cfht_fits_loader)
			return mask_profile.maskedFraction
		else:
			return 0.0


	def get_all_map_names(self):
		"""
		Builds a list with all the names of the maps to be analyzed, for each subfield and smoothing scale

		"""

		if type(self.model) in [CFHTemu1,CFHTcov]:
			
			realizations = range(1,self.options.getint("analysis","num_realizations")+1)
			self.map_names = self.model.getNames(realizations=realizations,subfield=self.subfield,smoothing=self.smoothing_scale)

			if type(self.model)==CFHTemu1:
				self.full_save_path = os.path.join(self.save_path,self.cosmo_id,self.subfield_name,self.smoothing_name)
			else:
				self.full_save_path = os.path.join(self.save_path,self.cosmo_id+"_cov",self.subfield_name,self.smoothing_name)
		
		elif type(self.model) == CFHTLens:
			
			self.map_names = [self.model.getName(subfield=self.subfield,smoothing=self.smoothing_scale)]

			if self.kwargs["mean_subtract"]:
				self.full_save_path = os.path.join(self.save_path,"observations_meansub",self.subfield_name,self.smoothing_name)
			else:
				self.full_save_path = os.path.join(self.save_path,"observations",self.subfield_name,self.smoothing_name)
		
		else:
			raise TypeError("Your model is not supported in this analysis!")

	def measure(self,pool=None):
		"""
		Measures the features specified in the Indexer for all the maps whose names are calculated by get_all_map_names; saves the ensemble results in numpy array format

		"""

		#Build the ensemble
		ens = Ensemble.fromfilelist(self.map_names)

		#Load the data into the ensemble by calling the measurer on each map
		ens.load(callback_loader=self.measurer,pool=pool,**self.kwargs)

		#Break the ensemble into sub-ensemble, one for each feature
		single_feature_ensembles = ens.split(self.kwargs["index"])

		#For each of the sub_ensembles, save it in the appropriate directory
		for n,ensemble in enumerate(single_feature_ensembles):
			ensemble.save(os.path.join(self.full_save_path,self.kwargs["index"][n].name) + ".npy")



#######################################################
###############Main execution##########################
#######################################################

if __name__=="__main__":

	#Parse command line options
	parser = argparse.ArgumentParser()
	parser.add_argument("-f","--file",dest="options_file",action="store",type=str,help="analysis options file")
	parser.add_argument("-v","--verbose",dest="verbose",action="store_true",default=False,help="turn on verbosity")
	parser.add_argument("-m","--mean_subtract",dest="mean_subtract",action="store_true",default=False,help="subtract the mean pixel value from the maps")

	cmd_args = parser.parse_args()

	if cmd_args.options_file is None:
		parser.print_help()
		sys.exit(0)

	#Set verbosity level
	if cmd_args.verbose:
		logging.basicConfig(level=logging.DEBUG)
	else:
		logging.basicConfig(level=logging.INFO)

	#Initialize MPIPool
	try:
		pool = MPIPool()
	except:
		pool = None

	if (pool is not None) and not(pool.is_master()):
		
		pool.wait()
		pool.comm.Barrier()
		MPI.Finalize()
		sys.exit(0)

	#Set progressbar attributes
	widgets = ["Progress: ",progressbar.Percentage(),' ',progressbar.Bar(marker="+")]

	#Parse INI options file
	options = ConfigParser.ConfigParser()
	with open(cmd_args.options_file,"r") as configfile:
		options.readfp(configfile)

	#Read the save path from options
	save_path = options.get("analysis","save_path")

	#Get the names of all the simulated models available for the CFHT analysis, including smoothing scales and subfields (CFHTemu1)
	all_simulated_models = CFHTemu1.getModels(root_path=options.get("simulations","root_path"))

	#Get also the CFHTcov model instance, to measure the covariance matrix
	covariance_model = CFHTcov.getModels(root_path=options.get("simulations","root_path"))

	#Get also the observation model instance
	observation = CFHTLens(root_path=options.get("observations","root_path"))

	#Select subset of (simulations,covariance,observations)
	if options.getboolean("analysis","measure_simulations"):
		models = all_simulated_models
	else:
		models = list()

	if options.getboolean("analysis","measure_simulations_covariance"):
		models.append(covariance_model)

	if options.getboolean("analysis","measure_observations"):
		models.append(observation)

	#Subfields and smoothing scales
	subfields = [ int(subfield) for subfield in options.get("analysis","subfields").split(",") ]
	smoothing_scales = [options.getfloat("analysis","smoothing_scale")]

	#Build an Indexer instance, that will contain info on all the features to measure, including binning, etc... (read from options)
	feature_list = list()

	if options.has_section("power_spectrum"):
		l_edges = np.ogrid[options.getfloat("power_spectrum","lmin"):options.getfloat("power_spectrum","lmax"):(options.getint("power_spectrum","num_bins")+1)*1j]
		np.save(os.path.join(save_path,"ell.npy"),0.5*(l_edges[1:]+l_edges[:-1]))
		feature_list.append(PowerSpectrum(l_edges))

	if options.has_section("moments"):
		feature_list.append(Moments())

	if options.has_section("peaks"):
		th_peaks = np.ogrid[options.getfloat("peaks","th_min"):options.getfloat("peaks","th_max"):(options.getint("peaks","num_bins")+1)*1j]
		np.save(os.path.join(save_path,"th_peaks.npy"),0.5*(th_peaks[1:]+th_peaks[:-1]))
		feature_list.append(Peaks(th_peaks))

	if options.has_section("minkowski_functionals"):
		th_minkowski = np.ogrid[options.getfloat("minkowski_functionals","th_min"):options.getfloat("minkowski_functionals","th_max"):(options.getint("minkowski_functionals","num_bins")+1)*1j]
		np.save(os.path.join(save_path,"th_minkowski.npy"),0.5*(th_minkowski[1:]+th_minkowski[:-1]))
		feature_list.append(MinkowskiAll(th_minkowski))

	idx = Indexer.stack(feature_list)

	#Write an info file with all the analysis information
	with open(os.path.join(save_path,"INFO.txt"),"w") as infofile:
		infofile.write(write_info(options))

	#Build the progress bar
	pbar = progressbar.ProgressBar(widgets=widgets,maxval=len(models)*len(subfields)*len(smoothing_scales)).start()
	i = 0

	#Cycle through the models and perform the measurements of the selected features (create the appropriate directories to save the outputs)
	for model in models:

		if type(model)==CFHTemu1:
			dir_to_make = os.path.join(save_path,model._cosmo_id_string)
		elif type(model)==CFHTcov:
			dir_to_make = os.path.join(save_path,model._cosmo_id_string+"_cov")
		elif type(model) == CFHTLens:
			if cmd_args.mean_subtract:
				dir_to_make = os.path.join(save_path,"observations_meansub")
			else:
				dir_to_make = os.path.join(save_path,"observations")
		else:
			raise TypeError("Your model is not supported in this analysis!")

		base_model_dir = dir_to_make
		
		if not os.path.exists(dir_to_make):
			os.mkdir(dir_to_make)

		for subfield in subfields:

			dir_to_make = os.path.join(base_model_dir,"subfield{0}".format(subfield))
			if not os.path.exists(dir_to_make):
				os.mkdir(dir_to_make)

			for smoothing_scale in smoothing_scales:

				dir_to_make = os.path.join(base_model_dir,"subfield{0}".format(subfield),"sigma{0:02d}".format(int(smoothing_scale*10)))
				if not os.path.exists(dir_to_make):
					os.mkdir(dir_to_make)
	
				m = Measurement(model=model,options=options,subfield=subfield,smoothing_scale=smoothing_scale,measurer=cfht_convergence_measure_all,index=idx,mean_subtract=cmd_args.mean_subtract)
				m.get_all_map_names()
				m.measure(pool=pool)

				i+=1
				pbar.update(i)
	
	pbar.finish()
	logging.info("DONE!")

	if pool is not None:
		
		pool.close()
		pool.comm.Barrier()
		MPI.Finalize()
	
	sys.exit(0)


