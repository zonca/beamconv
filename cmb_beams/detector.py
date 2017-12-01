import sys
import time
import warnings
import glob
import inspect
import numpy as np
import tools

class Beam(object):
    '''
    A class representing detector centroid and beam information
    '''
    def __init__(self, az=0., el=0., polang=0., name=None,
         pol='A', btype='Gaussian', fwhm=None, lmax=700, mmax=None,
         dead=False, ghost=False, amplitude=1., po_file=None, 
         eg_file=None, cross_pol_file=None):
        '''
        Keyword arguments
        ---------
        az : float 
            Azimuthal location of detector relative to boresight
            in degrees (default : 0.)
        el : float 
            Elevation location of detector relative to boresight
            in degrees (default : 0.)
        polang : float (default: 0.)
            The polarization orientation of the beam/detector [deg]
        name : str (default: None)
            The callsign of this particular beam
        pol : str (default: A)
            The polarization callsign of the beam (A or B)
        dead : bool (default: False)
            True if the beam is dead (not functioning)
        btype : str (default: Gaussian)
            Type of detector spatial response model. Can be one of three
            Gaussian : A symmetric Gaussian beam, definied by centroids and FWHM
            Gaussian_map : A symmetric Gaussian, defined by centroids and a map
            EG       : An elliptical Gaussian
            PO       : A realistic beam based on optical simulations or beam maps
        fwhm : float 
            Detector beam FWHM in arcmin (default : 43)
        lmax : int
            Bandlimit beam. If None, use 1.4*2*pi/fwhm. (default : None)
        mmax : int 
            Azimuthal band-limit beam. If None, use lmax (default : None)
        ghost : bool
            Whether the beam is a ghost or not (default : False)
        amplitude : scalar
            Total throughput of beam, i.e. integral of beam over the sphere. 
            ( \int d\omega B(\omega) Y_00(\omega) \equiv amplitude ). This
            means that b00 = amplitude / sqrt(4 pi) (default : 1.)
        po_file : str, None
            Absolute or relative path to .npy file with blm array for the
            (unpolarized) Physical Optics beam (default : None)
        eg_file : str, None
            Absolute or relative path to .npy file with blm array for the
            (unpolarized) Elliptical Gaussian beam (default : None)
        cross_pol_file : str, None
            Absolute or relative path to .npy file
            containing the cross polarization blm
            (default : None)
        '''

        self.az = az
        self.el = el
        self.polang = polang
        self.name = name
        self.pol = pol
        self.btype = btype
        self.dead = dead
        self.amplitude = amplitude
        self.po_file = po_file
        self.eg_file = eg_file
        self.cross_pol_file = cross_pol_file

        self.lmax = lmax           
        self.mmax = mmax
        self.fwhm = fwhm

        self.__ghost = ghost
        # ghosts are not allowed to have ghosts
        if not self.ghost:
            self.__ghosts = []
            self.ghost_count = 0
        if self.ghost:
            # if two ghosts share ghost_idx, they share blm
            self.ghost_idx = 0

    @property
    def ghost(self):
        return self.__ghost

    @property
    def ghosts(self):
        return self.__ghosts

    @property
    def ghost_count(self):
        return self.__ghost_count

    @ghost_count.setter
    def ghost_count(self, count):
        if not self.ghost:
            self.__ghost_count = count
        else:
            raise ValueErrror("ghost cannot have ghost_count")

    @property
    def ghost_idx(self):
        return self.__ghost_idx

    @ghost_idx.setter
    def ghost_idx(self, val):
        if self.ghost:
            self.__ghost_idx = val
        else:
            raise ValueError("main beam cannot have ghost_idx")

    @property
    def dead(self):
        return self.__dead

    @dead.setter
    def dead(self, val):
        '''
        Make sure ghosts are also declared dead when main beam is
        '''
        self.__dead = val
        try:
            for ghost in self.ghosts:
                ghost.__dead = val
        except AttributeError:
            # instance is ghost
            pass

    @property
    def lmax(self):
        return self.__lmax
    
    @lmax.setter
    def lmax(self, val):
        '''
        Make sure lmax is >= 0 and defaults to something sensible
        '''
        if val is None and fwhm:
            # Going up to 1.4 naieve Nyquist frequency set by beam scale 
            self.__lmax = int(2 * np.pi / np.radians(self.fwhm/60.) * 1.4)
        else:
            self.__lmax = max(val, 0)

    @property
    def fwhm(self):
        return self.__fwhm

    @fwhm.setter
    def fwhm(self, val):
        '''
        Set beam fwhm. Returns absolute value of 
        input and returns 1.4 * 2 * pi / lmax if
        fwhm is None.        
        '''
        if not val and self.lmax:
            val = (1.4 * 2. * np.pi) / self.lmax
            self.__fwhm = np.degrees(val) * 60
        else:
            self.__fwhm = np.abs(val)
            
    @property
    def mmax(self):
        return self.__mmax

    @mmax.setter
    def mmax(self, mmax):
        '''
        Set mmax to lmax if not set        
        '''
        self.__mmax = min(i for i in [mmax, self.lmax] \
                              if i is not None)

    @property
    def blm(self):
        '''
        Get blm arrays by either creating them or 
        loading them (depending on `btype` attr.

        Notes
        -----
        If blm attribute is already initialized and 
        btype is changes, blm will not be updated,
        first delete blm attribute in that case.
        '''
        try:
            return self.__blm
        except AttributeError:

            if self.btype == 'Gaussian':
                self.gen_gaussian_blm()
                return self.__blm

            else:
                # NOTE, you do not propagate c2, deconv_q, normalize
                # options, you can make them attributes in __init??

                if self.btype == 'PO':
                    self.load_blm(self.po_file, deconv_q=True, normalize=True)
                    return self.__blm

                elif self.btype == 'EG':
                    self.load_blm(self.eg_file, deconv_q=True, normalize=True)
                    return self.__blm

                else:
                    raise ValueError("btype = {} not recognized".format(self.btype))

    @blm.setter
    def blm(self, val):
        self.__blm = val

    @blm.deleter
    def blm(self):
        del self.__blm

    def __str__(self):

        return "name   : {} \nbtype  : {} \nalive  : {} \nFWHM"\
            "   : {} arcmin \naz     : {} deg \nel     : {} deg "\
            "\npolang : {} deg\n".format(self.name, self.btype,
            str(not self.dead), self.fwhm, self.az, self.el,
            self.polang)

    def gen_gaussian_blm(self):
        '''
        Generate symmetric Gaussian beam coefficients
        (I and pol) using FWHM and lmax.

        Notes
        -----
        harmonic coefficients are multiplied by factor
        sqrt(4 pi / (2 ell + 1)) and scaled by 
        `amplitude` attribute (see `Beam.__init__()`).
        '''
        
        blm = tools.gauss_blm(self.fwhm, self.lmax, pol=False)
        if self.amplitude != 1:
            blm *= self.amplitude
        blm = tools.get_copol_blm(blm, c2_fwhm=self.fwhm)

        self.btype = 'Gaussian'
        self.blm = blm

    def load_blm(self, filename, cross_pol_file=None, **kwargs):
        '''
        Load a .npy file containing a blm array, 
        and use array to populate `blm` attribute.

        Arguments
        ---------
        filename : str
            Absolute or relative path to file

        Keyword arguments
        -----------------
        cross_pol_file : str, None
            Absolute or relative path to .npy file
            containing the cross polarization blm
            (default : None)
        kwargs : {tools.get_copol_blm_opts}

        Notes
        -----
        Loaded blm are automatically scaled by given the `amplitude` 
        attribute.
        '''
        
        if cross_pol_file is None:
            # assume co-polarized beam

#            if filename is None:

                # Default to the blm_file attribute
#                if btype == 'PO' and isinstance(self.po_file, basestring):
#                    filename = self.self.po_file
#                else:
#                    raise ValueError(
#                        "Neither `filename` nor `blm_file` attribute given")
                        
            blm = np.load(filename)

            if self.amplitude != 1:
                # scale beam if needed
                blm *= self.amplitude

            # create spin \pm 2 components
            self.blm = tools.get_copol_blm(blm, **kwargs)

        else:
            raise NotImplementedError("be patient")

    def create_ghost(self, tag='ghost', **kwargs):
        '''
        Append a ghost Beam object to the `ghosts` attribute.
        This method will raise an error when called from a 
        ghost Beam object.

        Keyword Arguments
        -----------------
        tag : str
            Identifier string appended like <name>_<tag>
            where <name> is parent beam's name. If empty string,
            or None, just use parent Beam name. (default : ghost)            
        kwargs : {beam_opts}
        
        Notes
        ----
        Valid Keyword arguments are those accepted by 
        `Beam.__init__()` with the exception of `name`,
        which is ignored and `ghost`, which is always set.
        Unspecified kwargs are copied from parent beam.
        '''
        
        if self.ghost:
            raise RuntimeError('Ghost cannot have ghosts')

        parent_name = self.name
        kwargs.pop('name', None)
        if tag:
            if parent_name:
                name = parent_name + ('_' + tag)
            else:
                name = tag
        else:
            name = parent_name

        # mostly default to parent kwargs
        ghost_opts = dict(az=self.az,
                           el=self.el,
                           polang=self.polang,
                           name=name,
                           pol=self.pol,
                           btype=self.btype,
                           fwhm=self.fwhm,
                           dead=self.dead,                          
                           lmax=self.lmax,
                           mmax=self.mmax)

        # update options with specified kwargs
        ghost_opts.update(kwargs)
        ghost_opts.update(dict(ghost=True))
        ghost = Beam(**ghost_opts)

        # set ghost_idx
        ghost.ghost_idx = self.ghost_count
        self.ghost_count += 1

        self.ghosts.append(ghost)

    def reuse_blm(self, partner):
        '''
        Copy pointers to already initialized beam by
        another Beam instance. If both beams are 
        ghosts, beam takes partner's `ghost_idx`.

        Arguments
        ---------
        partner : Beam object
        '''
        
        if not isinstance(partner, Beam):
            raise TypeError('partner must be Beam object')

        if partner.ghost and self.ghost:
            self.ghost_idx = partner.ghost_idx

        self.blm = partner.blm
        self.btype = partner.btype
        self.lmax = partner.lmax
        self.mmax = partner.mmax
        self.amplitude = partner.amplitude

    def delete_blm(self, del_ghosts_blm=False):
        '''
        Remove the `blm` attribute of the object. Does the same
        for ghosts, if specified.

        Keyword arguments
        -----------------
        del_ghost_blm : bool
            If True, also remove blm attributes of all ghosts
        '''

        try:
            del(self.blm)
        except AttributeError:
            # no blm attribute to begin with
            pass

        if any(self.ghosts) and del_ghosts_blm:
            for ghost in self.ghosts:
                try:
                    del(ghost.blm)
                except AttributeError:
                    pass

    def get_offsets(self):
        '''
        Return (unrotated) detector offsets. 
        
        Returns
        -------
        az : float
            Azimuth of offset in degrees
        el : float
            Elevation of offset in degrees
        polang : float 
            Polarization angle in degrees

        Notes
        -----
        Detector offsets are defined
        as the sequence Rz(polang), Ry(el), Rx(az). Rz is defined 
        as the rotation around the boresight by angle `polang`
        which is measured relative to the southern side of 
        the local meridian in a clockwise manner when looking 
        towards the sky (Rh rot.), (i.e. the `Healpix convention`). 
        Followed by Ry and Rx, which are rotations in elevation 
        and azimuth with respect to the local horizon and meridian.
        '''
        
        return self.az, self.el, self.polang

class Detector():
    '''
    An object representing a CMB bolometer. Attribute describe detector
    sensitivity, frequency, and spatial response.


    '''

    def __init__(self, pol=True, single_moded=True, nu=100, bw=0.3, oe=0.4,
        fwhm=43, alt=5.2, et=None, NEP_phonon=6, NEP_readout=3, NEP_photon=None,
        P_opt=0, P_atm=None, P_cmb =0.3,  site_dir='old_profiles/', site=None):
        '''

        Arguments
        ----------

        pol : Bool (default: True)
            Is the detector polarized
        single_moded : Bool (default: True)
            Is the detector single moded. Currently, the code only knows
            how to deal with single moded detectors
        nu : float (default: 100) [GHz]
            The detector center frequency
        be : float (default: 0.3)
            Fractional spectral bandwidth
        oe : float (default: 0.4)
            Optical efficiency

        '''

        self.pol = pol
        self.polfact = 1.0 if self.pol else 2.0
        self.nu = nu
        self.bw = bw
        self.oe = oe
        self.fwhm = fwhm

        # Optical properties
        self.bsa = 2*pi*(pi/180/60*(self.fwhm/2.354))**2
        self.effa = (c/(self.nu*1e9))**2/self.bsa*1e4 # Effective area in cm^2

        # Note that you don't need fwhm
        if single_moded:
            self.et = (c/(1e9*self.nu))**2
        else:
            self.et = self.bsa*self.effa/1e4

        # Photon loading of various sorts
        self.P_opt = P_opt                        # pW
        self.P_cmb = P_cmb                        # pW
        self.site_dir = site_dir
        self.site = site
        if site is None and P_atm is None:
            raise ValueError('Must define site or atmospheric loading')

        if site is not None:
            self.P_atm = site_loading(self, site, site_dir=self.site_dir) # pW

        self.P_photon = self.oe * (self.P_atm + self.P_cmb + self.P_opt)
        self.dqdt = self.oe*dqdt(self.nu, bw=self.bw, pol=self.pol)

        # NEP's
        if NEP_photon is None:
            # aW/rHz
            self.NEP_bose = np.sqrt(2*self.P_photon**2 \
                /(self.polfact*self.nu*self.bw*1e9)) * 1e6
            self.NEP_shot = np.sqrt(2*hg*self.nu*self.P_photon) * 1e6
            self.NEP_photon = np.sqrt(self.NEP_bose**2 + self.NEP_shot**2)
        else:
            self.NEP_photon = NEP_photon        # aW/rHz

        self.NEP_phonon = NEP_phonon            # aW/rHz
        self.NEP_readout = NEP_readout          # aW/rHz
        self.NEP_detector = np.sqrt(NEP_phonon**2 + NEP_readout**2)
        self.NEP_total = np.sqrt(self.NEP_phonon**2 + self.NEP_readout**2
            +self.NEP_photon**2)                # aW/rHz

        self.NET = self.NEP_total/(np.sqrt(2)*self.dqdt)