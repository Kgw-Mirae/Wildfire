c======================================================================
c     program moment
c     Originated from In-Young Lee
c     Further developed by Jae-Jin Kim and Jong-Jin Baik    (2001.05.21)
c       major developments
c         1. 1.5 turbulence closure scheme
c         2. inclusion of thermodynamic energy equation
c         3. non-uniform grid system
c         4. momentum boundary condition
c     Further modified by Jae-Jin Kim                       (2007.05.29)
c         1. wall boundary condition
c----------------------------------------------------------------------c
c     F90 version  by Hyun-Gyu Kang                         (2017.06.14)
c----------------------------------------------------------------------c
c     Parallelized by Hyun-Gyu Kang                      
c     - Split in X direction version 1.0                    (2017.07.04) 
c     - Some bugs are fixed                                 (2017.08.28)
c     - revised inflow condition                            (2021.05.21)
c=======================================================================
c----------------------------------------------------------------------!
c--------- input_mod by_GK 2022.08-------------------------------------!
c----------------------------------------------------------------------!
      MODULE input_mod
      IMPLICIT NONE
      PUBLIC
      CHARACTER(LEN=500) :: TOPFILE
      CHARACTER(LEN=500) :: AFCFILE  !Cut
      CHARACTER(LEN=500) :: TREEFILE, LADFILE, FRACFILE  !tree
      CHARACTER(LEN=500) :: FIREFILE  !fire
      CHARACTER(LEN=500) :: EMISSFILE  !fire
      CHARACTER(LEN=500) :: RDAPSRESULTDIR
      CHARACTER(LEN=500) :: RESULTDIR

      REAL    :: N_time, N_delt, N_tend, N_winter,N_fire
      REAL    :: N_xint, N_yint, N_zint
      INTEGER :: N_irun, N_iwind, N_ither, N_iconc, N_itree
      INTEGER :: N_YYDD
      REAL    :: N_Sct, N_Prt

      CHARACTER(LEN=200) :: FILENAME='./input.namelist'
      CHARACTER(LEN= 80) :: NULL
      INTEGER :: IOS
      INTEGER :: IO_namelist = 2
      INTEGER :: IO_TOP      = 3
      INTEGER :: IO_AFC      = 4
      INTEGER :: IO_WRF_U    = 7
      INTEGER :: IO_WRF_V    = 8
      INTEGER :: IO_WRF_T    = 9
      INTEGER :: IO_TREE     =20
      INTEGER :: IO_LAD     =21
      INTEGER :: IO_FRAC     =22
      INTEGER :: IO_FIRE     =23
      INTEGER :: IO_EMISS     =24

      INTEGER :: IO_RESULTS  = 11

      PUBLIC :: READ_INPUT_FILE, MAKE_RDAPS_PATH, MAKE_RESULT_PATH
      PUBLIC :: CELSIUS_TO_KELVIN
      PUBLIC :: ADVANCE_DATE

      CONTAINS
       SUBROUTINE READ_INPUT_FILE
        NAMELIST /TIMEINFO/ N_time,N_delt,N_tend,N_winter,N_fire,N_YYDD
        NAMELIST /INPUTFILE/ TOPFILE,AFCFILE,TREEFILE,LADFILE,FRACFILE
     & ,FIREFILE,EMISSFILE,RDAPSRESULTDIR,RESULTDIR
        NAMELIST /DOMAININFO/ N_xint,N_yint,N_zint
        NAMELIST /MOMENTINFO/ N_irun,N_iconc, N_iwind,N_ither,N_itree ,
     &N_sct,  N_prt

        RDAPSRESULTDIR = '../1_RDAPS/txt_results'
        RESULTDIR = './results'
        N_xint = -1.
        N_yint = -1.
        N_zint = -1.

        ! READ NAMELIST
        OPEN(IO_namelist,FILE=TRIM(FILENAME),IOSTAT=IOS)
        READ(IO_namelist, TIMEINFO)
        READ(IO_namelist, INPUTFILE)
        READ(IO_namelist, DOMAININFO)
        READ(IO_namelist, MOMENTINFO)
        ! END

        IF (N_xint .LE. 0. .OR. N_yint .LE. 0. .OR.
     &      N_zint .LE. 0.) THEN
          PRINT *, 'ERROR: DOMAININFO N_xint/N_yint/N_zint ',
     &             'must be positive'
          STOP
        END IF

        !CLOSE(IO_namelist)
       END SUBROUTINE  READ_INPUT_FILE

c     Advance YYYYMMDD by one calendar day (including leap years).
       SUBROUTINE ADVANCE_DATE(YYDD)
        INTEGER, INTENT(INOUT) :: YYDD
        INTEGER :: YR, MO, DA
        INTEGER :: MDAYS(12)
        LOGICAL :: LEAP

        YR = YYDD / 10000
        MO = MOD(YYDD / 100, 100)
        DA = MOD(YYDD, 100)

        IF (MO .LT. 1 .OR. MO .GT. 12) THEN
          PRINT *, 'ERROR: invalid month in YYDD: ', YYDD
          STOP 1
        END IF

        MDAYS = (/31,28,31,30,31,30,31,31,30,31,30,31/)
        LEAP = (MOD(YR,400) .EQ. 0) .OR.
     &         (MOD(YR,4) .EQ. 0 .AND. MOD(YR,100) .NE. 0)
        IF (LEAP) MDAYS(2) = 29

        IF (DA .LT. 1 .OR. DA .GT. MDAYS(MO)) THEN
          PRINT *, 'ERROR: invalid day in YYDD: ', YYDD
          STOP 1
        END IF

        DA = DA + 1
        IF (DA .GT. MDAYS(MO)) THEN
          DA = 1
          MO = MO + 1
          IF (MO .GT. 12) THEN
            MO = 1
            YR = YR + 1
          END IF
        END IF
        YYDD = YR * 10000 + MO * 100 + DA
       END SUBROUTINE ADVANCE_DATE

       FUNCTION MAKE_RDAPS_PATH(PREFIX,YYDD,HH,SUFFIX) RESULT(PATH)
        CHARACTER(LEN=*), INTENT(IN) :: PREFIX, SUFFIX
       INTEGER, INTENT(IN) :: YYDD, HH
       CHARACTER(LEN=500) :: PATH
        INTEGER :: N, OUT_YYDD, OUT_HH
        INTEGER :: YR, MO, DA
        INTEGER :: MDAYS(12)
        LOGICAL :: LEAP

        OUT_YYDD = YYDD
        OUT_HH = HH

        DO WHILE (OUT_HH .GE. 24)
          OUT_HH = OUT_HH - 24
          YR = OUT_YYDD / 10000
          MO = MOD(OUT_YYDD / 100, 100)
          DA = MOD(OUT_YYDD, 100)
          MDAYS = (/31,28,31,30,31,30,31,31,30,31,30,31/)
          LEAP = (MOD(YR,400) .EQ. 0) .OR.
     &           (MOD(YR,4) .EQ. 0 .AND. MOD(YR,100) .NE. 0)
          IF (LEAP) MDAYS(2) = 29

          DA = DA + 1
          IF (DA .GT. MDAYS(MO)) THEN
            DA = 1
            MO = MO + 1
            IF (MO .GT. 12) THEN
              MO = 1
              YR = YR + 1
            END IF
          END IF
          OUT_YYDD = YR * 10000 + MO * 100 + DA
        END DO

        N = LEN_TRIM(RDAPSRESULTDIR)
        IF (N .GT. 0 .AND.
     &      (RDAPSRESULTDIR(N:N) .EQ. '/' .OR.
     &       RDAPSRESULTDIR(N:N) .EQ. '\')) THEN
          WRITE(PATH,'(A,A,I8.8,I2.2,A)') TRIM(RDAPSRESULTDIR),
     &         TRIM(PREFIX),OUT_YYDD,OUT_HH,TRIM(SUFFIX)
        ELSE
          WRITE(PATH,'(A,"/",A,I8.8,I2.2,A)') TRIM(RDAPSRESULTDIR),
     &         TRIM(PREFIX),OUT_YYDD,OUT_HH,TRIM(SUFFIX)
        END IF
       END FUNCTION MAKE_RDAPS_PATH

       FUNCTION MAKE_RESULT_PATH(YYDD,HH,MM) RESULT(PATH)
        INTEGER, INTENT(IN) :: YYDD, HH, MM
        CHARACTER(LEN=500) :: PATH
        INTEGER :: N, OUT_YYDD, OUT_HH, OUT_MM
        INTEGER :: YR, MO, DA
        INTEGER :: MDAYS(12)
        LOGICAL :: LEAP

        OUT_YYDD = YYDD
        OUT_HH = HH
        OUT_MM = MM

        DO WHILE (OUT_MM .GE. 60)
          OUT_MM = OUT_MM - 60
          OUT_HH = OUT_HH + 1
        END DO

        DO WHILE (OUT_HH .GE. 24)
          OUT_HH = OUT_HH - 24
          YR = OUT_YYDD / 10000
          MO = MOD(OUT_YYDD / 100, 100)
          DA = MOD(OUT_YYDD, 100)
          MDAYS = (/31,28,31,30,31,30,31,31,30,31,30,31/)
          LEAP = (MOD(YR,400) .EQ. 0) .OR.
     &           (MOD(YR,4) .EQ. 0 .AND. MOD(YR,100) .NE. 0)
          IF (LEAP) MDAYS(2) = 29

          DA = DA + 1
          IF (DA .GT. MDAYS(MO)) THEN
            DA = 1
            MO = MO + 1
            IF (MO .GT. 12) THEN
              MO = 1
              YR = YR + 1
            END IF
          END IF
          OUT_YYDD = YR * 10000 + MO * 100 + DA
        END DO

        N = LEN_TRIM(RESULTDIR)
        IF (N .GT. 0 .AND.
     &      (RESULTDIR(N:N) .EQ. '/' .OR.
     &       RESULTDIR(N:N) .EQ. '\')) THEN
          WRITE(PATH,'(A,"output_",I8.8,I2.2,I2.2,".dat")')
     &         TRIM(RESULTDIR),OUT_YYDD,OUT_HH,OUT_MM
        ELSE
          WRITE(PATH,'(A,"/output_",I8.8,I2.2,I2.2,".dat")')
     &         TRIM(RESULTDIR),OUT_YYDD,OUT_HH,OUT_MM
        END IF
       END FUNCTION MAKE_RESULT_PATH

       FUNCTION CELSIUS_TO_KELVIN(VALUE) RESULT(KVALUE)
        REAL, INTENT(IN) :: VALUE
        REAL :: KVALUE

        KVALUE = VALUE + 273.15
       END FUNCTION CELSIUS_TO_KELVIN

      END MODULE input_mod
c----------------------------------------------------------------------!


      module moment_dim_para
      include '../data/Domain/moment_domain.inc'
      integer,parameter :: imax1=imax+1,jmax1=jmax+1,kmax1=kmax+1
      integer,parameter :: imax2=imax+2,jmax2=jmax+2,kmax2=kmax+2
      integer,parameter :: itotal=imax2*jmax2*kmax2,maxits=1000,ipmx=62
      integer :: p_itotal
      end module moment_dim_para
      !----------------------------------------------------------------!
      module moment_dim
      use moment_dim_para
      implicit none

      !--- common /grid/ ----------------------------------------------!
      real,dimension(imax2) :: dx,px
      real,dimension(jmax2) :: dy,py
      real,dimension(kmax2) :: dz,pz
      real,dimension(imax1) :: delx 
      real,dimension(jmax1) :: dely 
      real,dimension(kmax1) :: delz 
      integer,dimension(imax2,jmax2,kmax2) :: ija,ijb,ijc 
      integer,dimension(imax2,jmax2,kmax2) :: ita,itb,itc !tree
      real,dimension(imax2,jmax2,kmax2) :: afsa,afsb,afsc,afsv
      real,dimension(imax2,jmax2,kmax2) :: afaa,afab,afac,afav
      real,dimension(imax2,jmax2,kmax2) :: afba,afbb,afbc,afbv
      real,dimension(imax2,jmax2,kmax2) :: afca,afcb,afcc,afcv
      real,dimension(imax2,jmax2,kmax2) :: cdrag, tfrac, dleaf !HJ tree
      integer,dimension(imax2,jmax2,kmax2) :: ijna,ijnb,ijnc, ijfnc    !!add_n JH fire
      integer,dimension(imax2,jmax2)       :: ijnaa,ijnbb,ijncc, ijfncc !!add_n JH fire

!         real,allocatable,dimension(:)     :: p_delx,p_dx,p_px
         real,allocatable,dimension(:)     :: p_dely,p_dy,p_py
      integer,allocatable,dimension(:,:,:) :: p_ija,p_ijb,p_ijc
      integer,allocatable,dimension(:,:,:) :: p_ita,p_itb,p_itc !Tree
      integer,allocatable,dimension(:,:,:) :: p_ijna,p_ijnb,p_ijnc
      integer,allocatable,dimension(:,:,:) :: p_ijfnc  !!add_n JH fire
      real,allocatable,dimension(:,:,:) :: p_afsa,p_afsb,p_afsc,p_afsv
      real,allocatable,dimension(:,:,:) :: p_afaa,p_afab,p_afac,p_afav
      real,allocatable,dimension(:,:,:) :: p_afba,p_afbb,p_afbc,p_afbv
      real,allocatable,dimension(:,:,:) :: p_afca,p_afcb,p_afcc,p_afcv
      real,allocatable,dimension(:,:,:) :: p_cdrag, p_tfrac, p_dleaf !HJ tree
      integer,allocatable,dimension(:,:,:) :: infe,infw,infs,infn
      integer,allocatable,dimension(:,:,:) :: odevn 
      integer,allocatable,dimension(:,:,:) :: p_odevn 

      !--- common /cons/ ----------------------------------------------!
      real :: zmax,ymax,xmax,cutu,cutv,cutw,cutp,cutc 
      real :: cutt,tbmin,gravity,Prt,Pr,ustar,ve
      real :: ubmin, vbmin, wbmin, pbmin, cbmin, xint, yint, zint
      real :: Ebmin, Dbmin,cu,c1,c2,sigE,sigD,Sct
      real :: cp
      real :: cutE, cutD, tkapa,ynd,BD,z0
!      real :: tair, tsurface,z0
      real,dimension(imax2,jmax2,kmax2) :: ttsurface

      !--- common /data/ ----------------------------------------------!
      real    :: delt, time, omegag, omegap
      real    :: fire_update  ! HJ 
      real    :: tconc, visl, vism
      integer :: istart,iwind,iconc,irun,ither,itree,YYDD
      integer :: ref_3d, dc
      integer :: iheatstart,iheatend,jheatstart,jheatend
      integer :: iloca1, iloca2, iloca3, iloca4, iloca5,iloca6, iloca7
      real,dimension(imax2,jmax2,kmax2) :: uin, vin, tkein, tmpin  !!add,change
      real,dimension(imax2,jmax2,kmax2) :: ws,dir  !!add,change
      real,dimension(imax2,jmax2) :: tsurfin  !! add,change
      real,allocatable,dimension(:,:,:) :: fire_3d ! fire
      real,allocatable,dimension(:,:,:) :: emiss_3d  !! HJ
      integer,allocatable,dimension(:) :: fire_HH, fire_MM
      real,allocatable,dimension(:) :: fire_inter  !! HJ
      integer :: fire_ntime
      integer :: ifixflux_wind, ifixflux_temp, HH
      character(len=256) :: filenames
      real :: fix_v !!add_n

      !--- common /coef/ ----------------------------------------------!
      real,allocatable,dimension(:,:,:) :: al,as,aw,ae,an,ah,s
     &                                    ,apx,apy,apz,app,apco
     &                                    ,aptt,apEE,apDD

      real,allocatable,dimension(:,:,:) :: p_al,p_as,p_aw,p_ae,p_an,p_ah
     &                                    ,p_s,p_apx,p_apy,p_apz,p_app 
     &                                    ,p_apco,p_aptt,p_apEE,p_apDD
     &                 , p_spx,p_spy,p_spz,p_spEp,p_spEu,p_spDp,p_spDu !tree
      !--- common /flow/ ----------------------------------------------!
        ! Array for master
      real,allocatable,dimension(:,:,:) :: uu,vv,ww,co
     &                                    ,uuo,vvo,wwo,coo,po 
     &                                    ,pdot,tt,tto,Qheat
     &                                    ,EE,EEo,DD,DDo
     &                                    ,tair,ref,sum_ref,ave_ref !!add,ref
     &                                    ,dum, fire_2d,emiss_2d  !! HJ

        ! Array for worker
      real,allocatable,dimension(:,:,:) :: p_uu,p_vv,p_ww,p_co
     &                                    ,p_uuo,p_vvo,p_wwo,p_coo,p_po 
     &                                    ,p_pdot,p_tt,p_tto,p_Qheat
     &                                    ,p_tair,p_ref        !! add,ref
     &                                    ,p_sum_ref,p_ave_ref !! add,ref
     &                                    ,p_EE,p_EEo,p_DD,p_DDo

      real,allocatable,dimension(:,:,:) :: p_fire_2d          !! HJ
      real,allocatable,dimension(:,:,:) :: p_emiss_2d          !! HJ

        ! Array for all
      real,allocatable,dimension(:,:,:) :: p_dum 


      !--- common /phys/ ----------------------------------------------!
      real,allocatable,dimension(:,:,:) :: vis,dena,denao,diff
     &                                    ,scE,scE1,scE2,scD,visee
     &                                    ,visdd,gam,spu,spv,spw,spE
     &                                    ,spD,swE,swD,spT,swT    

      real,allocatable,dimension(:,:,:) :: p_vis,p_dena,p_denao,p_diff
     &                                    ,p_scE,p_scE1,p_scE2,p_scD
     &                                    ,p_visee,p_visdd,p_gam,p_spu
     &                                    ,p_spv,p_spw,p_spE,p_spD,p_swE
     &                                    ,p_swD,p_spT,p_swT,p_vit
      end module moment_dim
!----------------------------------------------------------------------!      
      module common_mpi
      implicit none
      !****************************************************************!
      include 'mpif.h'
      !****************************************************************!
      integer,parameter :: master=0,from_master=1,from_worker=2
      integer :: status(MPI_STATUS_SIZE),ierr,ncpu,rank,nworker
      integer :: request,is,ie,is_u,ie_u,iss,iee
      integer,allocatable,dimension(:) :: p_imax,p_imax1,p_imax2 
                                          ! #grid per CPU in X dir.
      integer,allocatable,dimension(:) :: stag,rtag,scpu,rcpu
      integer,allocatable,dimension(:) :: req,sreq,rreq
                                          ! send and recv tags
      integer,allocatable,dimension(:) :: p_xloc_s ,p_xloc_e
      integer,allocatable,dimension(:) :: p_xloc1_s,p_xloc1_e
      integer,allocatable,dimension(:) :: p_xloc2_s,p_xloc2_e
      integer,allocatable,dimension(:) :: p_is_u,p_ie_u
      integer,allocatable,dimension(:) :: p_is_o,p_ie_o
      integer,allocatable,dimension(:) :: p_is_g,p_ie_g
      
      ! For test : multiple send & recv
      integer,allocatable,dimension(:) :: p_w2w_cpu
      end module common_mpi
!======================================================================!      
      use moment_dim
      use common_mpi
      use input_mod ! GK
      !----------------------------------------------------------------!
      real :: sum0,sum1,sum2,sum3,sum4,sum5,sum6,sum7,sum8,sum9
      real :: sum10,sum11,sum12,sum13,sum14,sum15
      real :: imax_per_cpu,tmp1,tmp2,tmp3
      integer :: nstep, out_unit
      integer :: boundary_due
      real    :: tend
      real    :: next_output_time, output_start_offset

      integer :: i,j,k,l,m,n,t,tim
      real(kind=8) :: stime,etime,time_sum
      character(8) :: f1020
      character(24) :: f1030
      character(520) :: outname

c MPI initialization
      call MPI_INITIALIZATION


c MPI array allocataion 
      call MPI_ALLOCATION


!----------------------------------------------------------------------!
      CALL READ_INPUT_FILE !GK
      call read_moment_fire_ntime(
     . '../0_fireline/result_fireline/'//
     . 'fire_intensity_timeseries_info.txt', fire_ntime)
      allocate(fire_3d(imax2,jmax2,fire_ntime))
      allocate(emiss_3d(imax2,jmax2,fire_ntime))
      allocate(fire_HH(fire_ntime),fire_MM(fire_ntime))
      allocate(fire_inter(fire_ntime))

      n = 0
      tstep = 1

      if ( rank == master ) then ! MASTER !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

      open(IO_TOP,file=TRIM(TOPFILE),IOSTAT=IOS)  !GK
      open(IO_AFC,file=TRIM(AFCFILE),IOSTAT=IOS)
      open(IO_TREE,file=TRIM(TREEFILE),IOSTAT=IOS) !tree
      open(IO_LAD,file=TRIM(LADFILE),IOSTAT=IOS) !tree
      open(IO_FRAC,file=TRIM(FRACFILE),IOSTAT=IOS) !tree
      open(IO_FIRE,file=TRIM(FIREFILE),IOSTAT=IOS) !fire
      open(IO_EMISS,file=TRIM(EMISSFILE),IOSTAT=IOS) !emission

      PRINT*, "INPUT ============================================"
      PRINT*, "TOPFILE     ==  ", TRIM(TOPFILE)
      PRINT*, "AFCFILE     ==  ", TRIM(AFCFILE)
      PRINT*, "TREEFILE    ==  ", TRIM(TREEFILE) ! JH 
      PRINT*, "LADFILE     ==  ", TRIM(LADFILE) ! JH 
      PRINT*, "FRACFILE    ==  ", TRIM(FRACFILE) ! JH 
      PRINT*, "FIREFILE    ==  ", TRIM(FIREFILE) ! JH 
      PRINT*, "EMISSFILE   ==  ", TRIM(EMISSFILE) ! JH 
   
      endif ! MASTER !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

c     data apx,apy,apz,app,apco,apEE,apDD,aptt/itotal*100.,itotal*100.,
c    .  itotal*100.,itotal*100.,itotal*100.,itotal*100.,
c    .  itotal*100.,itotal*100./

c  time:   time
c  delt:   time step
c  tend:   end of the simulation time
c  winter: writing time interval
!      time   = N_time   !GK
      delt   = N_delt   !GK
!      tend   = N_tend   !GK
      winter = N_winter !GK
      out_unit = IO_RESULTS
      YYDD = N_YYDD
       
c  omegag: relaxation coefficient for momentum correction
c  omegap: relaxation coefficient for pressure correction
c  errcut: cutoff value used to end iterative approximation
      omegag = 0.20
      omegap = 0.20
      errcut = 1.e-1

c  irun  = 0 for standard k-e turbulence closure scheme
c        = 1 for RNG run
c  iconc = 0 for no calculation of concentration evolution
c        = 1 for calculation of concentration evolution
c            tconc: starting time of pollutant emission
c  iwind = 0 for no wind calculations
c        = 1 for calculation of wind field
c  ither = 0 for no calculation of thermodynamic energy equation
c        = 1 for calculation of thermodynamic energy equation
c  iloca1  for upwind building wall heating
c  iloca2  for downwind building wall heating
c  iloca3  for south building wall heating
c  iloca4  for north building wall heating
c  iloca5  for building-top heatings
c  iloca6  for only a street-canyon bottom heating
c  iloca7  for ceiling heating
c  iheatstart = start index for heating location in x-direction  
c  iheatend   = end index for heating location in x-direction  
c  jheatstart = start index for heating location in y-direction  
c  jheatend   = end index for heating location in y-direction
c  tair = temperature of the ambient air
c  tsurface = temperature of the heating surface  
change *********
      irun   = N_irun !GK
      iconc  = N_iconc !HJ
      tconc  = 600.
      iwind  = N_iwind !GK
      ither  = N_ither !GK
      itree = N_itree !HJ tree
      iloca1 = 0
      iloca2 = 0
      iloca3 = 0
      iloca4 = 0
      iloca5 = 0
      iloca6 = 0
      iloca7 = 0

      ref_3d = 1
      tim = 1
      dc = 0
c  ubmin: allowable relative error for uu in percent
c  vbmin: allowable relative error for vv in percent
c  wbmin: allowable relative error for ww in percent
c  pbmin: allowable relative error for pdot in percent
c  cbmin: allowable relative error for co in percent
      ubmin = 1.e-2
      vbmin = 1.e-2
      wbmin = 1.e-3
      pbmin = 1.e-2
      cbmin = 1.e-4
      Ebmin = 1.e-4
      Dbmin = 1.e-4
      tbmin = 1.e-3

c  cutu: cut off values for uu
c  cutv: cut off values for vv
c  cutw: cut off values for ww
c  cutp: cut off values for pdot
c  cutc: cut off values for co
      cutu = 1.e-4
      cutv = 1.e-4
      cutw = 1.e-4
      cutp = 1.e-5
      cutc = 1.e-8
      cutE = 1.e-8
      cutD = 1.e-8
      cutt = 1.e-4

c  rhoo: air density [20oC]
c  xint: grid interval in x direction
c  yint: grid interval in y direction
c  zint: grid interval in z direction
      rhoo = 1.2
      xint = N_xint
      yint = N_yint
      zint = N_zint

c define coefficients
c Sct: Schmidt number
c Pr : Laminar Prandtl Number at 20 oC
c Prt: Turbulent Prandtl Number
c ynd: Non-dimensional length
c cp : Specific Heat at constant pressure [J/kg/K]
      tkapa = 0.4
      Sct = N_Sct ! GK
      gravity = 9.8
      Pr  = 0.72
      Prt = N_Prt  !HJ
      BD = 2200.
      z0 = 0.05
      ynd = 11.63
      cp  = 1012.
!       [W m-2]      [kW m-2]

      if(irun.eq.1) then
        cu = 0.0845
        c1 = 1.42
        c2 = 1.68
        sigE = 0.7179
        sigD = 0.7179
      else
        cu = 0.09
        c1 = 1.44
        c2 = 1.92
        sigE = 1.0
        sigD = 1.3
      endif

c  visl: kinematic viscosity of air [20oC] [m2/s]
c  vism: dynamic viscosity of air [20oC] [kg/m/s]
c  vise: eddy viscosity
c  viso: sum of laminar and eddy viscosity
c  gamo: viso for scalar variables
      visl = 1.50e-5
      vism = 1.81e-5
      vise = eddy*rhoo
      viso = visl+vise
      gamo = 1.*viso

c  ija(i,j,k): indices for integration of x-component winds
c  ijb(i,j,k): indices for integration of y-component winds
c  ijc(i,j,k): indices for integration of z-component winds and
c                          scalar variables





      do 120 k=1,kmax2
      do 120 j=1,jmax2
      do 120 i=1,imax2
      ija(i,j,k) = 1
      ijb(i,j,k) = 1
      ijc(i,j,k) = 1
      ita(i,j,k) = 1 !tree
      itb(i,j,k) = 1 !tree
      itc(i,j,k) = 1 !tree
      afsa(i,j,k) = 1.
      afsb(i,j,k) = 1.
      afsc(i,j,k) = 1.
      afsv(i,j,k) = 1.
      afaa(i,j,k) = 1.
      afab(i,j,k) = 1.
      afac(i,j,k) = 1.
      afav(i,j,k) = 1.
      afba(i,j,k) = 1.
      afbb(i,j,k) = 1.
      afbc(i,j,k) = 1.
      afbv(i,j,k) = 1.
      afca(i,j,k) = 1.
      afcb(i,j,k) = 1.
      afcc(i,j,k) = 1.
      afcv(i,j,k) = 1.
      cdrag(i,j,k) = 1.
      tfrac(i,j,k) = 1.
      dleaf(i,j,k) = 1.
  120 continue

      if ( rank == master ) then ! MASTER !!!!!!!!!!!!!!!!!!!!!!!!!!!!!

      write(f1020,'(a1,i3,a1,i1,a1)')'(',imax2,'i',1,')'
      write(f1030,'(a1,i3,a10)')'(',imax2,'(1x,f4.2))'

      do 130 k=1,ktop1
      read(IO_AFC,1000) adum,bdum
  130 read(IO_AFC,f1030) ((afsa(i,j,k),i=1,imax2),j=jmax2,1,-1)

      do 140 k=1,ktop1
      read(IO_TOP,1000) adum,bdum
  140 read(IO_TOP,f1020) ((ijc(i,j,k),i=1,imax2),j=jmax2,1,-1)

      do 150 k=1,ktop1
      read(IO_AFC,1000) adum,bdum
  150 read(IO_AFC,f1030) ((afsb(i,j,k),i=1,imax2),j=jmax2,1,-1)

      do 160 k=1,ktop1
      read(IO_TOP,1000) adum,bdum
  160 read(IO_TOP,f1020) ((ija(i,j,k),i=1,imax2),j=jmax2,1,-1)

      do 170 k=1,ktop1
      read(IO_AFC,1000) adum,bdum
  170 read(IO_AFC,f1030) ((afsc(i,j,k),i=1,imax2),j=jmax2,1,-1)

      do 180 k=1,ktop1
      read(IO_TOP,1000) adum,bdum
  180 read(IO_TOP,f1020) ((ijb(i,j,k),i=1,imax2),j=jmax2,1,-1)

      do 181 k=1,ktop1
      read(IO_AFC,1000) adum,bdum
  181 read(IO_AFC,f1030) ((afsv(i,j,k),i=1,imax2),j=jmax2,1,-1)

      do 182 k=1,ktop1
      read(IO_AFC,1000) adum,bdum
  182 read(IO_AFC,f1030) ((afaa(i,j,k),i=1,imax2),j=jmax2,1,-1)
      do 183 k=1,ktop1
      read(IO_AFC,1000) adum,bdum
  183 read(IO_AFC,f1030) ((afab(i,j,k),i=1,imax2),j=jmax2,1,-1)
      do 184 k=1,ktop1
      read(IO_AFC,1000) adum,bdum
  184 read(IO_AFC,f1030) ((afac(i,j,k),i=1,imax2),j=jmax2,1,-1)
      do 185 k=1,ktop1
      read(IO_AFC,1000) adum,bdum
  185 read(IO_AFC,f1030) ((afav(i,j,k),i=1,imax2),j=jmax2,1,-1)

      do 186 k=1,ktop1
      read(IO_AFC,1000) adum,bdum
  186 read(IO_AFC,f1030) ((afba(i,j,k),i=1,imax2),j=jmax2,1,-1)
      do 187 k=1,ktop1
      read(IO_AFC,1000) adum,bdum
  187 read(IO_AFC,f1030) ((afbb(i,j,k),i=1,imax2),j=jmax2,1,-1)
      do 188 k=1,ktop1
      read(IO_AFC,1000) adum,bdum
  188 read(IO_AFC,f1030) ((afbc(i,j,k),i=1,imax2),j=jmax2,1,-1)
      do 189 k=1,ktop1
      read(IO_AFC,1000) adum,bdum
  189 read(IO_AFC,f1030) ((afbv(i,j,k),i=1,imax2),j=jmax2,1,-1)

      do 190 k=1,ktop1
      read(IO_AFC,1000) adum,bdum
  190 read(IO_AFC,f1030) ((afca(i,j,k),i=1,imax2),j=jmax2,1,-1)
      do 191 k=1,ktop1
      read(IO_AFC,1000) adum,bdum
  191 read(IO_AFC,f1030) ((afcb(i,j,k),i=1,imax2),j=jmax2,1,-1)
      do 192 k=1,ktop1
      read(IO_AFC,1000) adum,bdum
  192 read(IO_AFC,f1030) ((afcc(i,j,k),i=1,imax2),j=jmax2,1,-1)
      do 193 k=1,ktop1
      read(IO_AFC,1000) adum,bdum
  193 read(IO_AFC,f1030) ((afcv(i,j,k),i=1,imax2),j=jmax2,1,-1)

!TREE TOPO, HJ
      do 194 k=1,ktop1
      read(20,1000) adum,bdum
  194 read(20,f1020) ((itc(i,j,k),i=1,imax2),j=jmax2,1,-1)

      do 195 k=1,ktop1
      read(20,1000) adum,bdum
  195 read(20,f1020) ((ita(i,j,k),i=1,imax2),j=jmax2,1,-1)

      do 196 k=1,ktop1
      read(20,1000) adum,bdum
  196 read(20,f1020) ((itb(i,j,k),i=1,imax2),j=jmax2,1,-1)


      do 197 k=1,fire_ntime
      read(23,'(i2,1x,i2)') fire_HH(k), fire_MM(k)   !fire 
  197 read(23,*) ((fire_3d(i,j,k),i=1,imax2),j=jmax2,1,-1)

      do 198 k=1,fire_ntime
      read(24,1000) adum,bdum
  198 read(24,*) ((emiss_3d(i,j,k),i=1,imax2),j=jmax2,1,-1)


      do 121 j=1,jmax2
      do 121 i=1,imax2
      ijnaa(i,j) = 1
      ijnbb(i,j) = 1
      ijncc(i,j) = 1
      ijfncc(i,j) = 1 ! JH fire
  121 continue

      do 122 k=1,kmax2
      do 122 j=1,jmax2
      do 122 i=1,imax2
      ijna(i,j,k) = 1
      ijnb(i,j,k) = 1
      ijnc(i,j,k) = 1

      ijfnc(i,j,k) = 1 ! JH fire
      fire_2d(i,j,k) = 0.  ! HJ
      emiss_2d(i,j,k) = 0.  ! HJ
  122 continue


      do 124 k=1,kmax2
      do 124 j=1,jmax2
      do 124 i=1,imax2
      ijna(i,j,k) = ijnaa(i,j)
      ijnb(i,j,k) = ijnbb(i,j)
      ijnc(i,j,k) = ijncc(i,j)
  124 continue

      end if ! MASTER !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

! ----------------------- RUN TIME SETTING------------------------!
! -------------- Simulate from the first fireline time --------------!
      if (rank .eq. master) then

         do k=1,fire_ntime
            fire_inter(k)=fire_HH(k)*3600.0
     .                   +fire_MM(k)*60.0
         end do

         time = fire_inter(1)-delt
         tend = time+N_tend
         HH   = fire_HH(1)

      end if

      call MPI_BCAST(time,1,MPI_REAL,master,
     .               MPI_COMM_WORLD,ierr)
      call MPI_BCAST(tend,1,MPI_REAL,master,
     .               MPI_COMM_WORLD,ierr)
      call MPI_BCAST(HH,1,MPI_INTEGER,master,
     .               MPI_COMM_WORLD,ierr)
      call MPI_BCAST(YYDD,1,MPI_INTEGER,master,
     .               MPI_COMM_WORLD,ierr)

      output_start_offset = min(N_fire, winter)
      next_output_time = time + delt + output_start_offset

      if (rank .eq. master) then

        if(fire_MM(1).gt.30.) then
      filenames = MAKE_RDAPS_PATH('',YYDD,HH+1,'_u.dat')
      open(unit=IO_WRF_U,file=trim(filenames),status='old',
     .     action='read')

      filenames = MAKE_RDAPS_PATH('',YYDD,HH+1,'_v.dat')
      open(unit=IO_WRF_V,file=trim(filenames),status='old',
     .     action='read')

      filenames = MAKE_RDAPS_PATH('',YYDD,HH+1,'_tmp.dat')
      open(unit=IO_WRF_T,file=trim(filenames),status='old',
     .     action='read')
       else if (fire_MM(1).le.30.) then
      filenames = MAKE_RDAPS_PATH('',YYDD,HH,'_u.dat')
      open(unit=IO_WRF_U,file=trim(filenames),status='old',
     .     action='read')

      filenames = MAKE_RDAPS_PATH('',YYDD,HH,'_v.dat')
      open(unit=IO_WRF_V,file=trim(filenames),status='old',
     .     action='read')

      filenames = MAKE_RDAPS_PATH('',YYDD,HH,'_tmp.dat')
      open(unit=IO_WRF_T,file=trim(filenames),status='old',
     .     action='read')
       end if

      end if

! ----------------------------------------------------------------!

c  xmax: size of the model domain in x direction
c  ymax: size of the model domain in y direction
c  zmax: size of the model domain in z direction
      zmax  = zint*float(kmax)
      ymax  = yint*float(jmax)
      xmax  = xint*float(imax)


c  setup the grid system
c  done in master      
      if ( rank == master ) then ! MASTER !!!!!!!!!!!!!!!!!!!!!!!!!!!!!
cccccccccccccccc
      call grids
cccccccccccccccc

cccccccccccccccc
      call start
cccccccccccccccc
      end if ! MASTER !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!



       p_dena(:,:,:) = rhoo
      p_denao(:,:,:) = rhoo

      wot = 0.

c MPI distribution of initial fields and others used in timestepping 
 
      call MPI_VAR_DISTRIBUTION

cccccccccccccccc
      call inflow_condition 
cccccccccccccccc


c  start time integration

      time_sum = 0.d0

      nstep = 0
  400 time  = time+delt
      stime = MPI_WTIME() ! for time checking
      nstep = nstep + 1
      wot   = wot+1

      HH = int(time/3600.)  
      if (HH.ge.24) then
         HH = HH-24
      end if

      if (time .ge. 86400. .and. dc.eq.0) then
         CALL ADVANCE_DATE(YYDD)
         dc = 1
      end if


! ------------------------FIRE LINE UPDATE------------------------!

       if(rank.eq.master)then  !HJ
       if (tim .le. fire_ntime .and.
     .     abs(time-fire_inter(tim)).le.0.25) then
         do j=1,jmax2
           do i=1,imax2
                
            fire_2d(i,j,1) = fire_3d(i,j,tim)*1000.
            emiss_2d(i,j,1) = emiss_3d(i,j,tim)
           
           end do
         end do

         tim = tim + 1
!           if(tim.eq.11) then
!             tim = 10
!           end if
         print*, 'Fire line update'
       end if
       end if

      call SENDRECV_MASTER_WORKER(+1,fire_2d,p_fire_2d)    
      call SENDRECV_MASTER_WORKER(+1,emiss_2d,p_emiss_2d)  

! ----------------------------------------------------------------!




  420 continue


ccccccccccccccccccccccccccccccc
      if(iwind.eq.1) then
ccccccccccccccccccccccccccccccc
c compute viscosity


      do 110 k=2,kmax1
      do 110 j=p_is_u(rank),p_imax1(rank)
      do 110 i=2,imax1 ! 2~imax1

      if(p_ijc(i,j,k).ne.0) then
              
      if(irun.eq.1) then
      p_vis(i,j,k) = cu*p_EE(i,j,k)**2/p_DD(i,j,k) + visl
      endif

      endif

  110 continue

      if (irun.eq.1) then
      call UPDATE_BUFFER_REAL(p_vis)
      endif


      !%%%%%%%%%%%%%%%%%%%%%%%%%%
      call p_coefu

      call p_soruu

      call p_coefv
      call p_sorvv

      call p_coefw
      call p_sorww

      call p_coefp
      call p_sorpo

c  pressure and velocity correction
      call p_correc

      call p_coefE
      call p_sorEE

      call p_coefD
      call p_sorDD

      if (ither.eq.1) then
      call p_coeft
      call p_sortt
      endif
      !%%%%%%%%%%%%%%%%%%%%%%%%%%

cccccccccccccccccccccccccc      
      error_sum = 0.0
      call p_convrg(error)
cccccccccccccccccccccccccc      

      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
      call MPI_ALLREDUCE(error,error_sum,1,MPI_REAL,
     .                   MPI_SUM,MPI_COMM_WORLD,ierr)
      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

      if(error_sum.gt.errcut) go to 420

      end if ! if for iwind
cccccccccccccccccccccccccccc

      if(iconc.eq.1) then

      do 411 k= 2,kmax
      do 411 j= 2,p_imax1(rank)
      do 411 i= 1,imax2 ! 1~imax2
       if(p_ijc(i,j,k-1).eq.0 .and. p_ijc(i,j,k).ne.0) then  ! HJ
       if(p_emiss_2d(i,j,1) .ge. 0.05) then
 
 
        p_co(i,j,k)=p_co(i,j,k)+p_emiss_2d(i,j,1)
     .   /(xint*yint*zint*p_afsv(i,j,k))*delt ! emission     


!        print*, p_emiss_2d(i,j,1)/p_afsv(i,j,k), p_afsv(i,j,k)
      end if
      end if
  411 continue

ccccccccccccccccccccccccccc
      call p_coefc
      call p_sorco
ccccccccccccccccccccccccccc
      end if ! if for iconc


comment
      call SENDRECV_MASTER_WORKER(-1,uu,p_uu)    !HJ : WORKER -> MASTER 
     
      if (rank .eq. master) then
         write(*,123) YYDD,HH,
     .        int(mod(time,3600.0)/60.0),
     .        int(mod(time,60.0)),
     .        uu(100,100,15),
     .        uu(100,100,25),
     .        uu(100,100,35)
      end if

  123 format(I8.8,1X,I2.2,':',I2.2,':',I2.2,
     .       ' | U15=',F10.5,
     .       ' U25=',F10.5,
     .       ' U35=',F10.5)

      
      if (ref_3d == 0) then
      if (rank == master) then

      do k=1,kmax2
      do j=1,jmax2
      do i=1,imax2
      ref(i,j,k) = tt(i,j,k)
      end do
      end do
      end do

      do k = 1,kmax2
      do j = 1,jmax2
      do i = 1,imax2
      sum_ref(i,j,k) = 0.
      ave_ref(i,j,k) = 0.
      enddo
      enddo
      enddo

      do k=2,kmax1

      num_ref = 0

      do j=2,jmax1
      do i=2,imax1

        if(ijc(i,j,k).eq.1)then
         num_ref = num_ref+1
         sum_ref(2,2,k)=sum_ref(2,2,k) + tt(i,j,k)
        endif

      end do
      end do

        ave_ref(2,2,k) = sum_ref(2,2,k)/float(num_ref)


      end do

      do k=2,kmax1
      do j=2,jmax1
      do i=2,imax1
      ref(i,j,k) = ave_ref(2,2,k)
      end do
      end do
      end do


      end if

!      p_ref =0.0     ! add_ref

      call SENDRECV_MASTER_WORKER(+1,ref,p_ref) ! +1: MASTER->WORKER update to p_ref
      call UPDATE_BUFFER_REAL(p_ref)     ! add_ref

      end if

c  update values and calculate diffusivity
ccccccccccccccccc
      call p_update
ccccccccccccccccc


      if (time .ge. next_output_time - 0.25 .or.
     .    time .ge. tend) then
        n = n+1

      call SENDRECV_MASTER_WORKER(-1,uu  ,p_uu  )
      call SENDRECV_MASTER_WORKER(-1,vv  ,p_vv  )
      call SENDRECV_MASTER_WORKER(-1,ww  ,p_ww  )
!      call SENDRECV_MASTER_WORKER(-1,po  ,p_po  )
!      call SENDRECV_MASTER_WORKER(-1,pdot,p_pdot)
      call SENDRECV_MASTER_WORKER(-1,tt  ,p_tt  )
      call SENDRECV_MASTER_WORKER(-1,co  ,p_co  )
!      call SENDRECV_MASTER_WORKER(-1,vis ,p_vis )
      call SENDRECV_MASTER_WORKER(-1,EE  ,p_EE  )
!      call SENDRECV_MASTER_WORKER(-1,DD  ,p_DD  )
!      call SENDRECV_MASTER_WORKER(-1,tair  ,p_tair  )      ! add_ref
!      call SENDRECV_MASTER_WORKER(-1,ref  ,p_ref  )        ! add_ref
!      call SENDRECV_MASTER_WORKER(-1,sum_ref ,p_sum_ref  ) ! add_ref
!      call SENDRECV_MASTER_WORKER(-1,ave_ref ,p_ave_ref  ) ! add_ref
!      call SENDRECV_MASTER_WORKER(-1,fire_2d ,p_fire_2d  ) ! HJ
!      call SENDRECV_MASTER_WORKER(-1,emiss_2d ,p_emiss_2d  ) ! HJ

c writing interval; winter(sec)


!akoh
      if ( rank == master ) then ! MASTER !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

      outname = MAKE_RESULT_PATH(YYDD,HH,nint(mod(time,3600.0)/60.0))
       open(out_unit,file=trim(outname),status='replace',action='write')

      do 6000 k=1,kmax2
      do 6000 j=1,jmax2
      do 6000 i=1,imax2
      write(out_unit,5000)uu(i,j,k), vv(i,j,k), ww(i,j,k), tt(i,j,k)
     . ,co(i,j,k), EE(i,j,k)   
 5000 format(6f15.6)
 6000 continue

      close(out_unit)

        print *," write complete  :", trim(outname)


      endif ! MASTER !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!


      end if ! if for [time]

      do while (next_output_time .le. time + 0.25)
         next_output_time = next_output_time + winter
      end do

! ---------------------BOUNDARY UPDATE----------------------------!

      boundary_due = 0

      if (rank .eq. master) then
         if (time .lt. tend .and.
     .       int((time-delt+1800.)/3600.0) .lt.
     .       int((time+1800.)/3600.0)) then
            boundary_due = 1
         end if
      end if

      call MPI_BCAST(boundary_due,1,MPI_INTEGER,master,
     .               MPI_COMM_WORLD,ierr)

      if (boundary_due .eq. 1) then

         call SENDRECV_MASTER_WORKER(-1,uu,p_uu)
         call SENDRECV_MASTER_WORKER(-1,vv,p_vv)
         call SENDRECV_MASTER_WORKER(-1,tt,p_tt)

         if (rank .eq. master) then
            call boundary_update
            print *, 'Boundary update'
         end if

         call SENDRECV_MASTER_WORKER(+1,uu,p_uu)
         call SENDRECV_MASTER_WORKER(+1,vv,p_vv)
         call SENDRECV_MASTER_WORKER(+1,tt,p_tt)

      end if

! ----------------------------------------------------------------!


c  reset the dynamic pressure
      do 410 k=1,kmax2
      do 410 j=2,p_imax1(rank)
      do 410 i=1,imax2

  410 p_po(i,j,k) = 0.

      etime = MPI_WTIME()                  ! For time checking
      time_sum = time_sum + (etime-stime)  ! For time checking

      p_dum = p_uu
  723 format (10(x,F15.6))


      if(time.lt.tend) go to 400


      ! Save to check ----------------------------------!
      call SENDRECV_MASTER_WORKER(-1,dum,p_uu)
      if ( rank == master ) then
      open(11,file='coef_mpi.bin',status='unknown',access='direct',
     &     form='unformatted',recl=imax2*jmax2*kmax2*4)
      write(11,rec=1) dum 
      close(11)
      endif
      ! Save to check ----------------------------------!

      if ( rank == master ) then
      print*,'stop successfully'
      endif
      print*, rank,time_sum

 1000 format(2a4)
 1100 format(2e11.4)
 2200 format(e11.4,/,7e11.4,/,7e11.4)
 2300 format(6e11.4)

c MPI termination

      CALL MPI_FINALIZE(ierr)

      end 

      subroutine read_moment_fire_ntime(infofile, ntime)
      implicit none
      character(len=*), intent(in) :: infofile
      integer, intent(out) :: ntime
      character(len=256) :: line, keyword
      integer :: ios

      ntime = 0
      open(91,file=trim(infofile),status='old',action='read',
     .     iostat=ios)
      if (ios .ne. 0) then
         print *, 'ERROR: Cannot open fireline info file '
         print *, trim(infofile)
         stop
      end if

      do
         read(91,'(A)',iostat=ios) line
         if (ios .ne. 0) exit
         read(line,*,iostat=ios) keyword
         if (ios .ne. 0) cycle
         if (trim(keyword) .eq. 'NTIME') then
            read(line,*) keyword, ntime
            exit
         end if
      end do
      close(91)

      if (ntime .le. 0) then
         print *, 'ERROR: Invalid NTIME in fireline info file ',
     .            trim(infofile)
         stop
      end if

      return
      end

      


************************************************************************
* BEG of MPI related SUBROUTINEs ***************************************
************************************************************************

!----------------------------------------------------------------------!
!      
! MPI INITIALIZATION routine      
!      
! 1. MPI INITIALIZATION
! 2. Splitted loop indexing (X dir. in this version)
!    1) [ 2~p_imax(rank) ]              : [ 1~imax2 ] in serial
!    2) [ p_is_u(rank) ~ p_ie_u(rank) ] : [ 2~imax  ] in serial
!    2) [ p_is_o(rank) ~ p_ie_o(rank) ] : [ 2~imax1 ] in serial      
!    2) [ p_is_g(rank) ~ p_ie_g(rank) ] : [ 1~imax2 ] in serial      
!      
! 3. SEND and RECV rank and tag     
!      
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine MPI_INITIALIZATION
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      use moment_dim
      use common_mpi
      !----------------------------------------------------------------!
      implicit none
      integer :: i,j,k,isum1,itmp1,itmp2,itmp3,n
      
!----------------------------------------------------------------------!

      call MPI_INIT(ierr)
      call MPI_COMM_RANK(MPI_COMM_WORLD,rank,ierr)
      call MPI_COMM_SIZE(MPI_COMM_WORLD,nworker,ierr)

!     nworker = ncpu - 1

! CPU check  
      if ( rank == master ) then
        print*,'Nworkers      =',nworker
        print*,"Master's rank =",master
        print*
      endif

! Split imax into p_imax
!      itmp1 = imax2 / real(nworker)
!      itmp2 = int(imax2 - itmp1*nworker) ! Rest
      itmp1 = jmax2 / real(nworker)
      itmp2 = int(jmax2 - itmp1*nworker) ! Rest

      allocate(p_imax(0:nworker-1))
      allocate(p_imax1(0:nworker-1))
      allocate(p_imax2(0:nworker-1))

      p_imax(0:nworker-1) = itmp1

      ! add rest grids
      do i = 0,itmp2-1
        p_imax(i) = p_imax(i)+1
      end do

      ! p_imax1, p_imax2
      do n = 0,nworker-1
        p_imax1(n) = p_imax(n)+1
        p_imax2(n) = p_imax(n)+2
      end do

      ! X grid location
      allocate(p_xloc_s(0:nworker-1))
      allocate(p_xloc_e(0:nworker-1))

      itmp1 = p_imax(0)
      p_xloc_s(0) = 1
      p_xloc_e(0) = itmp1

      do n = 1,nworker-1
              itmp1 = itmp1 + p_imax(n)
        p_xloc_s(n) = itmp1 - p_imax(n) + 1
        p_xloc_e(n) = itmp1
      end do


      ! Start X & End X for parallel loop for u-grid (2~imax)
      allocate(p_is_u(0:nworker-1))
      allocate(p_ie_u(0:nworker-1))

      do n = 0,nworker-1
          if ( n == 0       ) then
        p_is_u(n) = 3 ; p_ie_u(n) = p_imax1(n)   ! 2 ~
      elseif ( n == nworker-1 ) then
        p_is_u(n) = 2 ; p_ie_u(n) = p_imax(n)-1 ! ~ imax
      else
        p_is_u(n) = 2 ; p_ie_u(n) = p_imax1(n)
      endif
      end do

      ! Start X & End X for parallel loop for other grid (2-imax1)
      allocate(p_is_o(0:nworker-1))
      allocate(p_ie_o(0:nworker-1))

      do n = 0,nworker-1
          if ( n == 0       ) then
        p_is_o(n) = 3 ; p_ie_o(n) = p_imax1(n) ! 2 ~
      elseif ( n == nworker-1 ) then
        p_is_o(n) = 2 ; p_ie_o(n) = p_imax(n)  ! ~ imax1
      else
        p_is_o(n) = 2 ; p_ie_o(n) = p_imax1(n)
      endif
      end do

      ! Start X & End X for parallel loop for other grid (1~imax2)
      allocate(p_is_g(0:nworker-1))
      allocate(p_ie_g(0:nworker-1))

      do n = 0,nworker-1
          if ( n == 0       ) then
        p_is_g(n) = 2 ; p_ie_g(n) = p_imax1(n) ! 1 ~
      elseif ( n == nworker-1 ) then
        p_is_g(n) = 2 ; p_ie_g(n) = p_imax1(n)  ! ~ imax2
      else
        p_is_g(n) = 2 ; p_ie_g(n) = p_imax1(n)
      endif
      end do


      ! itotal for each CPU 
      p_itotal = p_imax2(rank)*imax2*kmax2

      ! print for check 
      if ( rank == master ) then
      print*
      print*,'#Grid points in X dir for each CPU'
      print*,'proc  p_imax p_imax1 p_imax2'
      itmp1 = 0
      do i = 0,nworker-1
        itmp1 = itmp1 + p_imax(i)
        print('(5i6)'),i,p_imax(i),p_imax1(i),p_imax2(i)
      end do
      print*, itmp1

      print*
      print*,'X grid location for each CPU'
      print*,'proc    p_xs   p_xe' 
      do i = 0,nworker-1
        print('(3i6)'),i,p_xloc_s(i),p_xloc_e(i)
      end do
      endif 



!!kbs      call MPI_BARRIER(MPI_COMM_WORLD,ierr)
      if ( rank == 1 ) then
      print*
      print*,'Grid index start & end for u-grid'
      do n = 0,nworker-1
        print*, 'p_is ie',p_is_u(n),p_ie_u(n)
      end do

      print*
      print*,'Grid index start & end for other grid'
      do n = 0,nworker-1
        print*, 'p_is ie',p_is_o(n),p_ie_o(n)
      end do

      print*
      print*,'Grid index start & end for global grid'
      do n = 0,nworker-1
        print*, 'p_is ie',p_is_g(n),p_ie_g(n)
      end do
      endif


! SEND & RECV tags --------------------------------------------------!
!
! tag 1 = Left CPU ; tag 2 = Right CPU
!
!--------------------------------------------------------------------!
!      
!                     stag: n-1          stag: n+1
!                     rank: n-1          rank: n+1
!
!                       SEND                SEND
!           [        ] <------ [        ] ------> [        ]
!           [Core n-1]         [ Core n ]         [Core n+1]      
!           [        ] ------> [        ] <------ [        ]
!                       RECV                RECV          
!      
!                     rank: n-1          rank: n+1 
!                     rtag:   n          rtag:   n
!      
!---------------------------------------------------------------------

      allocate(stag(1:2))
      allocate(rtag(1:2))
      allocate(scpu(1:2))
      allocate(rcpu(1:2))

      if ( rank == 0 ) then
        scpu(1) = nworker-1 ; scpu(2) = rank+1
        rcpu(1) = nworker-1 ; rcpu(2) = rank+1
        stag(1) = nworker-1 ; stag(2) = rank+1 
        rtag(1) = rank      ; rtag(2) = rank

      elseif ( rank == nworker-1 ) then
        scpu(1) = rank-1 ; scpu(2) = 0
        rcpu(1) = rank-1 ; rcpu(2) = 0
        stag(1) = rank-1 ; stag(2) = 0 
        rtag(1) = rank   ; rtag(2) = rank

      else
        scpu(1) = rank-1 ; scpu(2) = rank+1
        rcpu(1) = rank-1 ; rcpu(2) = rank+1
        stag(1) = rank-1 ; stag(2) = rank+1 
        rtag(1) = rank   ; rtag(2) = rank
      endif

      allocate( req(1:4))
      allocate(sreq(1:2))
      allocate(rreq(1:2))
      
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      end subroutine MPI_INITIALIZATION
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc



!----------------------------------------------------------------------!
!      
! MPI ALLOCATION routine      
!      
! 1. Allocation of arrays for master 
!    (same arrays in serial code for grid and start)      
!      
! 2. Allocation of arrays for worker 
!    (arrays used for parallel CFD)      
!      
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine MPI_ALLOCATION
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      use moment_dim
      use common_mpi
!----------------------------------------------------------------------!


      if ( rank == master ) then ! MASTER !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

      ! Array for coef
      allocate(  al(imax2,jmax2,kmax2),  as(imax2,jmax2,kmax2),
     &           aw(imax2,jmax2,kmax2),  ae(imax2,jmax2,kmax2),
     &           an(imax2,jmax2,kmax2),  ah(imax2,jmax2,kmax2),
     &            s(imax2,jmax2,kmax2),
     &          apx(imax2,jmax2,kmax2), apy(imax2,jmax2,kmax2),
     &          apz(imax2,jmax2,kmax2), app(imax2,jmax2,kmax2),
     &         apco(imax2,jmax2,kmax2),
     &         aptt(imax2,jmax2,kmax2),apEE(imax2,jmax2,kmax2),
     &         apDD(imax2,jmax2,kmax2) )

      ! Array for flow
      allocate(   uu(imax2,jmax2,kmax2),   vv(imax2,jmax2,kmax2),
     &            ww(imax2,jmax2,kmax2),   co(imax2,jmax2,kmax2),
     &           uuo(imax2,jmax2,kmax2),  vvo(imax2,jmax2,kmax2),
     &           wwo(imax2,jmax2,kmax2),  coo(imax2,jmax2,kmax2),
     &            po(imax2,jmax2,kmax2), pdot(imax2,jmax2,kmax2),
     &            tt(imax2,jmax2,kmax2),  tto(imax2,jmax2,kmax2),
     &         Qheat(imax2,jmax2,kmax2),   EE(imax2,jmax2,kmax2),
     &           EEo(imax2,jmax2,kmax2),   DD(imax2,jmax2,kmax2),
     &          tair(imax2,jmax2,kmax2),  ref(imax2,jmax2,kmax2),     ! add_ref
     &       sum_ref(imax2,jmax2,kmax2),  ave_ref(imax2,jmax2,kmax2), ! add_ref
     &           DDo(imax2,jmax2,kmax2) , fire_2d(imax2,jmax2,kmax2),! HJ
     &         emiss_2d(imax2,jmax2,kmax2)) ! HJ

      ! Array for phys
      allocate(  vis(imax2,jmax2,kmax2), dena(imax2,jmax2,kmax2),
     &         denao(imax2,jmax2,kmax2), diff(imax2,jmax2,kmax2),
     &           scE(imax2,jmax2,kmax2), scE1(imax2,jmax2,kmax2),
     &          scE2(imax2,jmax2,kmax2),  scD(imax2,jmax2,kmax2),
     &         visee(imax2,jmax2,kmax2),visdd(imax2,jmax2,kmax2),
     &           gam(imax2,jmax2,kmax2),  spu(imax2,jmax2,kmax2),
     &           spv(imax2,jmax2,kmax2),  spw(imax2,jmax2,kmax2),
     &           spE(imax2,jmax2,kmax2),  spD(imax2,jmax2,kmax2),
     &           swE(imax2,jmax2,kmax2),  swD(imax2,jmax2,kmax2),
     &           spT(imax2,jmax2,kmax2),  swT(imax2,jmax2,kmax2) )


      allocate(  dum(imax2,jmax2,kmax2))
      
      ! Array for sor
      allocate(odevn(imax2,jmax2,kmax2))

      endif ! MASTER !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

!-----      

! Allocation of arrays used for MPI      



      ! Array for grid
      allocate(   p_dy(1:p_imax2(rank)))
      allocate(   p_py(1:p_imax2(rank)))
      allocate( p_dely(1:p_imax1(rank)))

      allocate( p_ija(imax2,1:p_imax2(rank),kmax2))
      allocate( p_ijb(imax2,1:p_imax2(rank),kmax2))
      allocate( p_ijc(imax2,1:p_imax2(rank),kmax2))
      allocate( p_ita(imax2,1:p_imax2(rank),kmax2)) !tree
      allocate( p_itb(imax2,1:p_imax2(rank),kmax2)) !tree
      allocate( p_itc(imax2,1:p_imax2(rank),kmax2)) !tree

      allocate( p_ijna(imax2,1:p_imax2(rank),kmax2)) !! add_n
      allocate( p_ijnb(imax2,1:p_imax2(rank),kmax2)) !! add_n
      allocate( p_ijnc(imax2,1:p_imax2(rank),kmax2)) !! add_n
      allocate( p_ijfnc(imax2,1:p_imax2(rank),kmax2)) !! add_n JH fire
      allocate( p_afsa(imax2,1:p_imax2(rank),kmax2))
      allocate( p_afsb(imax2,1:p_imax2(rank),kmax2))
      allocate( p_afsc(imax2,1:p_imax2(rank),kmax2))
      allocate( p_afsv(imax2,1:p_imax2(rank),kmax2))
      allocate( p_afaa(imax2,1:p_imax2(rank),kmax2))
      allocate( p_afab(imax2,1:p_imax2(rank),kmax2))
      allocate( p_afac(imax2,1:p_imax2(rank),kmax2))
      allocate( p_afav(imax2,1:p_imax2(rank),kmax2))
      allocate( p_afba(imax2,1:p_imax2(rank),kmax2))
      allocate( p_afbb(imax2,1:p_imax2(rank),kmax2))
      allocate( p_afbc(imax2,1:p_imax2(rank),kmax2))
      allocate( p_afbv(imax2,1:p_imax2(rank),kmax2))
      allocate( p_afca(imax2,1:p_imax2(rank),kmax2))
      allocate( p_afcb(imax2,1:p_imax2(rank),kmax2))
      allocate( p_afcc(imax2,1:p_imax2(rank),kmax2))
      allocate( p_afcv(imax2,1:p_imax2(rank),kmax2))
      allocate( p_cdrag(imax2,1:p_imax2(rank),kmax2)) !HJ tree
      allocate( p_tfrac(imax2,1:p_imax2(rank),kmax2)) !HJ tree
      allocate( p_dleaf(imax2,1:p_imax2(rank),kmax2)) !HJ tree

      allocate( infe(imax2,1:p_imax2(rank),kmax2))
      allocate( infw(imax2,1:p_imax2(rank),kmax2))
      allocate( infs(imax2,1:p_imax2(rank),kmax2))
      allocate( infn(imax2,1:p_imax2(rank),kmax2))

      ! Array for coef
      allocate(  p_al(imax2,1:p_imax2(rank),kmax2),  
     &           p_as(imax2,1:p_imax2(rank),kmax2),
     &           p_aw(imax2,1:p_imax2(rank),kmax2),  
     &           p_ae(imax2,1:p_imax2(rank),kmax2),
     &           p_an(imax2,1:p_imax2(rank),kmax2),  
     &           p_ah(imax2,1:p_imax2(rank),kmax2),
     &            p_s(imax2,1:p_imax2(rank),kmax2),
     &          p_apx(imax2,1:p_imax2(rank),kmax2), 
     &          p_apy(imax2,1:p_imax2(rank),kmax2),
     &          p_apz(imax2,1:p_imax2(rank),kmax2), 
     &          p_app(imax2,1:p_imax2(rank),kmax2),
     &         p_apco(imax2,1:p_imax2(rank),kmax2),
     &         p_aptt(imax2,1:p_imax2(rank),kmax2),
     &         p_apEE(imax2,1:p_imax2(rank),kmax2),
     &         p_apDD(imax2,1:p_imax2(rank),kmax2),
     &         p_spx(imax2,1:p_imax2(rank),kmax2),  !tree
     &         p_spy(imax2,1:p_imax2(rank),kmax2),  !tree
     &         p_spz(imax2,1:p_imax2(rank),kmax2),  !tree
     &         p_spEp(imax2,1:p_imax2(rank),kmax2),  !tree
     &         p_spEu(imax2,1:p_imax2(rank),kmax2),  !tree
     &         p_spDp(imax2,1:p_imax2(rank),kmax2),  !tree
     &         p_spDu(imax2,1:p_imax2(rank),kmax2)  !tree
     & )

      ! Array for flow
      allocate(   p_uu(imax2,1:p_imax2(rank),kmax2),   
     &            p_vv(imax2,1:p_imax2(rank),kmax2),
     &            p_ww(imax2,1:p_imax2(rank),kmax2),   
     &            p_co(imax2,1:p_imax2(rank),kmax2),
     &           p_uuo(imax2,1:p_imax2(rank),kmax2),
     &           p_vvo(imax2,1:p_imax2(rank),kmax2),
     &           p_wwo(imax2,1:p_imax2(rank),kmax2),
     &           p_coo(imax2,1:p_imax2(rank),kmax2),
     &            p_po(imax2,1:p_imax2(rank),kmax2), 
     &          p_pdot(imax2,1:p_imax2(rank),kmax2),
     &            p_tt(imax2,1:p_imax2(rank),kmax2),  
     &           p_tto(imax2,1:p_imax2(rank),kmax2),
     &          p_tair(imax2,1:p_imax2(rank),kmax2), ! add_ref
     &           p_ref(imax2,1:p_imax2(rank),kmax2), ! add_ref
     &       p_sum_ref(imax2,1:p_imax2(rank),kmax2), ! add_ref
     &       p_ave_ref(imax2,1:p_imax2(rank),kmax2), ! add_ref
     &       p_fire_2d(imax2,1:p_imax2(rank),kmax2), ! HJ       
     &       p_emiss_2d(imax2,1:p_imax2(rank),kmax2), ! HJ       
     &         p_Qheat(imax2,1:p_imax2(rank),kmax2),   
     &            p_EE(imax2,1:p_imax2(rank),kmax2),
     &           p_EEo(imax2,1:p_imax2(rank),kmax2),   
     &            p_DD(imax2,1:p_imax2(rank),kmax2),
     &           p_DDo(imax2,1:p_imax2(rank),kmax2) )

      ! Array for phys
      allocate(  p_vis(imax2,1:p_imax2(rank),kmax2), 
     &          p_dena(imax2,1:p_imax2(rank),kmax2),
     &         p_denao(imax2,1:p_imax2(rank),kmax2),
     &          p_diff(imax2,1:p_imax2(rank),kmax2),
     &           p_scE(imax2,1:p_imax2(rank),kmax2), 
     &          p_scE1(imax2,1:p_imax2(rank),kmax2),
     &          p_scE2(imax2,1:p_imax2(rank),kmax2),  
     &           p_scD(imax2,1:p_imax2(rank),kmax2),
     &         p_visee(imax2,1:p_imax2(rank),kmax2),
     &         p_visdd(imax2,1:p_imax2(rank),kmax2),
     &           p_gam(imax2,1:p_imax2(rank),kmax2),  
     &           p_spu(imax2,1:p_imax2(rank),kmax2),
     &           p_spv(imax2,1:p_imax2(rank),kmax2),
     &           p_spw(imax2,1:p_imax2(rank),kmax2),
     &           p_spE(imax2,1:p_imax2(rank),kmax2),  
     &           p_spD(imax2,1:p_imax2(rank),kmax2),
     &           p_swE(imax2,1:p_imax2(rank),kmax2),  
     &           p_swD(imax2,1:p_imax2(rank),kmax2),
     &           p_spT(imax2,1:p_imax2(rank),kmax2),  
     &           p_swT(imax2,1:p_imax2(rank),kmax2),
     &           p_vit(imax2,1:p_imax2(rank),kmax2) )

      ! Array for sor
      allocate(p_odevn(imax2,1:p_imax2(rank),kmax2))
      allocate(  p_dum(imax2,1:p_imax2(rank),kmax2))


cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      end subroutine MPI_ALLOCATION
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc


!----------------------------------------------------------------------!
!      
! MPI DISTRIBUTION routine
!
! 1. Distribution of arrays associated with 'grid'
! 2. Distribution of arrays associated with topo
! 3. Distribution of arrays associated with initial field 
!      
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine MPI_VAR_DISTRIBUTION
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      use moment_dim
      use common_mpi
      integer :: i,j,k,l,m,n
      real(kind=8) :: stime,etime
!----------------------------------------------------------------------!

! grid ----------------------------------------------------------------!

      ! BCAST of dx,px,dy,py,dz,pz,dely,delz
      call MPI_BCAST(dx  ,imax2,MPI_REAL4,master,MPI_COMM_WORLD,ierr)
      call MPI_BCAST(px  ,imax2,MPI_REAL4,master,MPI_COMM_WORLD,ierr)
      call MPI_BCAST(dy  ,jmax2,MPI_REAL4,master,MPI_COMM_WORLD,ierr)
      call MPI_BCAST(py  ,jmax2,MPI_REAL4,master,MPI_COMM_WORLD,ierr)
      call MPI_BCAST(dz  ,kmax2,MPI_REAL4,master,MPI_COMM_WORLD,ierr)
      call MPI_BCAST(pz  ,kmax2,MPI_REAL4,master,MPI_COMM_WORLD,ierr)
      call MPI_BCAST(delx,imax1,MPI_REAL4,master,MPI_COMM_WORLD,ierr)
      call MPI_BCAST(dely,jmax1,MPI_REAL4,master,MPI_COMM_WORLD,ierr)
      call MPI_BCAST(delz,kmax1,MPI_REAL4,master,MPI_COMM_WORLD,ierr)

      ! Get p_dy,p_py,p_dely

      !----
      if ( rank > 0 .and. rank < nworker-1 ) then
      is = p_xloc_s(rank) ; ie = p_xloc_e(rank)

      p_dy(2:p_imax1(rank)) = dy(is:ie)
      p_dy(1)               = dy(is-1) 
      p_dy(p_imax2(rank))   = dy(ie+1)
      
      p_py(2:p_imax1(rank)) = py(is:ie)
      p_py(1)               = py(is-1) 
      p_py(p_imax2(rank))   = py(ie+1)

      do i = 1,p_imax1(rank) 
      p_dely(i) = p_py(i+1)-p_py(i)
      end do

      endif

      !----
      if ( rank == 0 ) then
      is = p_xloc_s(rank) ; ie = p_xloc_e(rank)

      p_dy(1)               = 0.0
      p_dy(2:p_imax1(rank)) = dy(is:ie)
      p_dy(p_imax2(rank))   = dy(ie+1)

      p_py(1)               = 0.0
      p_py(2:p_imax1(rank)) = py(is:ie)
      p_py(p_imax2(rank))   = py(ie+1)

      do i = 1,p_imax1(rank) 
      p_dely(i) = p_py(i+1)-p_py(i)
      end do

      endif

      !----
      if ( rank == nworker-1 ) then
      is = p_xloc_s(rank) ; ie = p_xloc_e(rank)

      p_dy(1)               = dy(is-1) 
      p_dy(2:p_imax1(rank)) = dy(is:ie)
      p_dy(p_imax1(rank))   = 0.0
      p_dy(p_imax2(rank))   = 0.0
      
      p_py(1)               = py(is-1) 
      p_py(2:p_imax1(rank)) = py(is:ie)
      p_py(p_imax2(rank))   = 0.0 

      do i = 1,p_imax(rank)  !!! p_imax !!!
      p_dely(i) = p_py(i+1)-p_py(i)
      end do

      endif




      p_ija(:,:,:) = 1
      p_ijb(:,:,:) = 1
      p_ijc(:,:,:) = 1
      p_ita(:,:,:) = 1 !tree
      p_itb(:,:,:) = 1 !tree
      p_itc(:,:,:) = 1 !tree

      p_ijna(:,:,:) = 1  !! add_n
      p_ijnb(:,:,:) = 1  !! add_n
      p_ijnc(:,:,:) = 1  !! add_n
      p_ijfnc(:,:,:) = 1  !! add_n JH fire

      if ( rank == master ) then ! MASTER !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

        do n = 1,nworker-1
          is = p_xloc_s(n) ; ie = p_xloc_e(n)
          call MPI_SEND(ija(:,is:ie,:),
     &                  p_imax(n)*imax2*kmax2,MPI_INTEGER,
     &                  n,0,MPI_COMM_WORLD,ierr)
          call MPI_SEND(ijb(:,is:ie,:),
     &                  p_imax(n)*imax2*kmax2,MPI_INTEGER,
     &                  n,1,MPI_COMM_WORLD,ierr)
          call MPI_SEND(ijc(:,is:ie,:),
     &                  p_imax(n)*imax2*kmax2,MPI_INTEGER,
     &                  n,2,MPI_COMM_WORLD,ierr)

          call MPI_SEND(ita(:,is:ie,:),
     &                  p_imax(n)*imax2*kmax2,MPI_INTEGER,
     &                  n,0,MPI_COMM_WORLD,ierr) !tree
          call MPI_SEND(itb(:,is:ie,:),
     &                  p_imax(n)*imax2*kmax2,MPI_INTEGER,
     &                  n,1,MPI_COMM_WORLD,ierr) !tree
          call MPI_SEND(itc(:,is:ie,:),
     &                  p_imax(n)*imax2*kmax2,MPI_INTEGER,
     &                  n,2,MPI_COMM_WORLD,ierr) !tree


     !! add_n
          call MPI_SEND(ijna(:,is:ie,:),
     &                  p_imax(n)*imax2*kmax2,MPI_INTEGER,
     &                  n,0,MPI_COMM_WORLD,ierr)
          call MPI_SEND(ijnb(:,is:ie,:),
     &                  p_imax(n)*imax2*kmax2,MPI_INTEGER,
     &                  n,1,MPI_COMM_WORLD,ierr)
          call MPI_SEND(ijnc(:,is:ie,:),
     &                  p_imax(n)*imax2*kmax2,MPI_INTEGER,
     &                  n,2,MPI_COMM_WORLD,ierr)
          call MPI_SEND(ijfnc(:,is:ie,:), ! JH fire
     &                  p_imax(n)*imax2*kmax2,MPI_INTEGER,
     &                  n,2,MPI_COMM_WORLD,ierr)


        end do

          is = p_xloc_s(0) ; ie = p_xloc_e(0)
          p_ija(:,2:p_imax1(0),:) = ija(:,is:ie,:)
          p_ijb(:,2:p_imax1(0),:) = ijb(:,is:ie,:)
          p_ijc(:,2:p_imax1(0),:) = ijc(:,is:ie,:)
          p_ita(:,2:p_imax1(0),:) = ita(:,is:ie,:) !tree
          p_itb(:,2:p_imax1(0),:) = itb(:,is:ie,:) !tree
          p_itc(:,2:p_imax1(0),:) = itc(:,is:ie,:) !tree

          p_ijna(:,2:p_imax1(0),:) = ijna(:,is:ie,:)  !! add_n
          p_ijnb(:,2:p_imax1(0),:) = ijnb(:,is:ie,:)  !! add_n
          p_ijnc(:,2:p_imax1(0),:) = ijnc(:,is:ie,:)  !! add_n
          p_ijfnc(:,2:p_imax1(0),:) = ijfnc(:,is:ie,:)  !! add_n JH fire

      endif ! MASTER !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

!-----
      if ( rank > master ) then ! WORKER @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
      
      call MPI_RECV(p_ija(:,2:p_imax1(rank),:),
     &              p_imax(rank)*imax2*kmax2,MPI_INTEGER,
     &              master,0,MPI_COMM_WORLD,status,ierr)
      call MPI_RECV(p_ijb(:,2:p_imax1(rank),:),
     &              p_imax(rank)*imax2*kmax2,MPI_INTEGER,
     &              master,1,MPI_COMM_WORLD,status,ierr)
      call MPI_RECV(p_ijc(:,2:p_imax1(rank),:),
     &              p_imax(rank)*imax2*kmax2,MPI_INTEGER,
     &              master,2,MPI_COMM_WORLD,status,ierr)
      call MPI_RECV(p_ita(:,2:p_imax1(rank),:),
     &              p_imax(rank)*imax2*kmax2,MPI_INTEGER,
     &              master,0,MPI_COMM_WORLD,status,ierr) !tree
      call MPI_RECV(p_itb(:,2:p_imax1(rank),:),
     &              p_imax(rank)*imax2*kmax2,MPI_INTEGER,
     &              master,1,MPI_COMM_WORLD,status,ierr) !tree
      call MPI_RECV(p_itc(:,2:p_imax1(rank),:),
     &              p_imax(rank)*imax2*kmax2,MPI_INTEGER,
     &              master,2,MPI_COMM_WORLD,status,ierr) !tree

     !! add_n
      call MPI_RECV(p_ijna(:,2:p_imax1(rank),:),
     &              p_imax(rank)*imax2*kmax2,MPI_INTEGER,
     &              master,0,MPI_COMM_WORLD,status,ierr)
      call MPI_RECV(p_ijnb(:,2:p_imax1(rank),:),
     &              p_imax(rank)*imax2*kmax2,MPI_INTEGER,
     &              master,1,MPI_COMM_WORLD,status,ierr)
      call MPI_RECV(p_ijnc(:,2:p_imax1(rank),:),
     &              p_imax(rank)*imax2*kmax2,MPI_INTEGER,
     &              master,2,MPI_COMM_WORLD,status,ierr)
      call MPI_RECV(p_ijfnc(:,2:p_imax1(rank),:), ! JH fire
     &              p_imax(rank)*imax2*kmax2,MPI_INTEGER,
     &              master,2,MPI_COMM_WORLD,status,ierr)


      endif ! WORKER @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@

      ! Update buffer (ija,ijb,ijc)
      call UPDATE_BUFFER_INTEGER(p_ija)
      call UPDATE_BUFFER_INTEGER(p_ijb)
      call UPDATE_BUFFER_INTEGER(p_ijc)
      call UPDATE_BUFFER_INTEGER(p_ita) !tree
      call UPDATE_BUFFER_INTEGER(p_itb) !tree
      call UPDATE_BUFFER_INTEGER(p_itc) !tree

      call UPDATE_BUFFER_INTEGER(p_ijna) !! add_n
      call UPDATE_BUFFER_INTEGER(p_ijnb) !! add_n
      call UPDATE_BUFFER_INTEGER(p_ijnc) !! add_n
      call UPDATE_BUFFER_INTEGER(p_ijfnc) !! add_n JH fire


      call SENDRECV_MASTER_WORKER(+1,afsa,p_afsa)
      call SENDRECV_MASTER_WORKER(+1,afsb,p_afsb)
      call SENDRECV_MASTER_WORKER(+1,afsc,p_afsc)
      call SENDRECV_MASTER_WORKER(+1,afsv,p_afsv)
      call SENDRECV_MASTER_WORKER(+1,afaa,p_afaa)
      call SENDRECV_MASTER_WORKER(+1,afab,p_afab)
      call SENDRECV_MASTER_WORKER(+1,afac,p_afac)
      call SENDRECV_MASTER_WORKER(+1,afav,p_afav)
      call SENDRECV_MASTER_WORKER(+1,afba,p_afba)
      call SENDRECV_MASTER_WORKER(+1,afbb,p_afbb)
      call SENDRECV_MASTER_WORKER(+1,afbc,p_afbc)
      call SENDRECV_MASTER_WORKER(+1,afbv,p_afbv)
      call SENDRECV_MASTER_WORKER(+1,afca,p_afca)
      call SENDRECV_MASTER_WORKER(+1,afcb,p_afcb)
      call SENDRECV_MASTER_WORKER(+1,afcc,p_afcc)
      call SENDRECV_MASTER_WORKER(+1,afcv,p_afcv)
      call SENDRECV_MASTER_WORKER(+1,cdrag, p_cdrag) !HJ tree
      call SENDRECV_MASTER_WORKER(+1,tfrac, p_tfrac) !HJ tree
      call SENDRECV_MASTER_WORKER(+1,dleaf, p_dleaf) !HJ tree

      call UPDATE_BUFFER_REAL(p_afsa)
      call UPDATE_BUFFER_REAL(p_afsb)
      call UPDATE_BUFFER_REAL(p_afsc)
      call UPDATE_BUFFER_REAL(p_afsv)
      call UPDATE_BUFFER_REAL(p_afaa)
      call UPDATE_BUFFER_REAL(p_afab)
      call UPDATE_BUFFER_REAL(p_afac)
      call UPDATE_BUFFER_REAL(p_afav)
      call UPDATE_BUFFER_REAL(p_afba)
      call UPDATE_BUFFER_REAL(p_afbb)
      call UPDATE_BUFFER_REAL(p_afbc)
      call UPDATE_BUFFER_REAL(p_afbv)
      call UPDATE_BUFFER_REAL(p_afca)
      call UPDATE_BUFFER_REAL(p_afcb)
      call UPDATE_BUFFER_REAL(p_afcc)
      call UPDATE_BUFFER_REAL(p_afcv)
      call UPDATE_BUFFER_REAL(p_cdrag) !HJ tree
      call UPDATE_BUFFER_REAL(p_tfrac) !HJ tree
      call UPDATE_BUFFER_REAL(p_dleaf) !HJ tree

! Var: odevn ----------------------------------------------------------!

      p_odevn(:,:,:) = 0

      if ( rank == master ) then ! MASTER !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

      odevn(:,:,:) = 0
      do k = 2,kmax1
      do j = 2,jmax1
      do i = 2,imax1
        odevn(i,j,k) = mod(i+j+k,2) 
      end do
      end do
      end do
      
        do n = 1,nworker-1
          is = p_xloc_s(n) ; ie = p_xloc_e(n)
          call MPI_SEND(odevn(:,is:ie,:),
     &                  p_imax(n)*imax2*kmax2,MPI_INTEGER,
     &                  n,0,MPI_COMM_WORLD,ierr)
        end do

      is = p_xloc_s(0) ; ie = p_xloc_e(0)
      p_odevn(:,2:p_imax1(0),:) = odevn(:,is:ie,:)
      
      endif ! MASTER !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!


      if ( rank > master ) then ! WORKER @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
      
      call MPI_RECV(p_odevn(:,2:p_imax1(rank),:),
     &              p_imax(rank)*imax2*kmax2,MPI_INTEGER,
     &              master,0,MPI_COMM_WORLD,status,ierr)

      endif ! WORKER @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@

      call UPDATE_BUFFER_INTEGER(p_odevn)


! Initial condition ---------------------------------------------------!

      ! Bcast - ref
!      call MPI_BCAST(ref,kmax2,MPI_REAL4,master,MPI_COMM_WORLD,ierr)  !! add,change,ref


      ! co, coo, po, pdot -> zero at init

           p_co(:,:,:) = 0.0 
         p_pdot(:,:,:) = 0.0
          p_coo(:,:,:) = 0.0
           p_po(:,:,:) = 0.0 
      ! add initial
         p_uu=0.0
         p_uuo=0.0
         p_vv=0.0
         p_vvo=0.0
         p_ww=0.0
         p_wwo=0.0
         p_tt=0.0
         p_tto=0.0
         p_EE=0.0
         p_EEo=0.0
         p_DD=0.0
         p_DDo=0.0
         p_vis=0.0
         p_tair=0.0     ! add_ref
         p_ref =0.0     ! add_ref
         p_sum_ref =0.0 ! add_ref
         p_ave_ref =0.0 ! add_ref
         p_fire_2d = 0.0  ! HJ
         p_emiss_2d = 0.0  ! HJ

      call SENDRECV_MASTER_WORKER(+1,uu ,p_uu ) ! +1: MASTER->WORKER
      call SENDRECV_MASTER_WORKER(+1,uuo,p_uuo) ! +1: MASTER->WORKER
      call SENDRECV_MASTER_WORKER(+1,vv ,p_vv ) ! +1: MASTER->WORKER
      call SENDRECV_MASTER_WORKER(+1,vvo,p_vvo) ! +1: MASTER->WORKER
      call SENDRECV_MASTER_WORKER(+1,ww ,p_ww ) ! +1: MASTER->WORKER
      call SENDRECV_MASTER_WORKER(+1,wwo,p_wwo) ! +1: MASTER->WORKER
      call SENDRECV_MASTER_WORKER(+1,tt ,p_tt ) ! +1: MASTER->WORKER
      call SENDRECV_MASTER_WORKER(+1,tto,p_tto) ! +1: MASTER->WORKER
      call SENDRECV_MASTER_WORKER(+1,EE ,p_EE ) ! +1: MASTER->WORKER
      call SENDRECV_MASTER_WORKER(+1,EEo,p_EEo) ! +1: MASTER->WORKER
      call SENDRECV_MASTER_WORKER(+1,DD ,p_DD ) ! +1: MASTER->WORKER
      call SENDRECV_MASTER_WORKER(+1,DDo,p_DDo) ! +1: MASTER->WORKER
      call SENDRECV_MASTER_WORKER(+1,vis,p_vis) ! +1: MASTER->WORKER
      call SENDRECV_MASTER_WORKER(+1,tair,p_tair) ! +1: MASTER->WORKER !add_ref
      call SENDRECV_MASTER_WORKER(+1,ref,p_ref)   ! +1: MASTER->WORKER !add_ref
      call SENDRECV_MASTER_WORKER(+1,sum_ref,p_sum_ref) !+1:MASTER->WORKER !add_ref
      call SENDRECV_MASTER_WORKER(+1,ave_ref,p_ave_ref) !+1:MASTER->WORKER !add_ref
      call SENDRECV_MASTER_WORKER(+1,fire_2d,p_fire_2d) ! HJ, +1: MASTER->WORKER
      call SENDRECV_MASTER_WORKER(+1,emiss_2d,p_emiss_2d) ! HJ, +1: MASTER->WORKER



      call UPDATE_BUFFER_REAL(p_uu )
      call UPDATE_BUFFER_REAL(p_uuo)
      call UPDATE_BUFFER_REAL(p_vv )
      call UPDATE_BUFFER_REAL(p_vvo)
      call UPDATE_BUFFER_REAL(p_ww )
      call UPDATE_BUFFER_REAL(p_wwo)
      call UPDATE_BUFFER_REAL(p_tt )
      call UPDATE_BUFFER_REAL(p_tto)
      call UPDATE_BUFFER_REAL(p_EE )
      call UPDATE_BUFFER_REAL(p_EEo)
      call UPDATE_BUFFER_REAL(p_DD )
      call UPDATE_BUFFER_REAL(p_DDo)
      call UPDATE_BUFFER_REAL(p_vis)
      call UPDATE_BUFFER_REAL(p_tair)    ! add_ref
      call UPDATE_BUFFER_REAL(p_ref)     ! add_ref
      call UPDATE_BUFFER_REAL(p_sum_ref) ! add_ref
      call UPDATE_BUFFER_REAL(p_ave_ref) ! add_ref
      call UPDATE_BUFFER_REAL(p_fire_2d) ! HJ 
      call UPDATE_BUFFER_REAL(p_emiss_2d) ! HJ 

!----------------------------------------------------------------------!

cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      end subroutine MPI_VAR_DISTRIBUTION
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc

!----------------------------------------------------------------------!
!      
! MPI UPDATE BUFFER REAL routine
!
! - Update buffer for a given 'real' variable
!
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
!     subroutine UPDATE_BUFFER_REAL (p_var)
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
!     use moment_dim
!     use common_mpi
!     implicit none
!     real,dimension(p_imax2(rank),jmax2,kmax2) :: p_var
!     integer :: sreq1,sreq2,rreq1,rreq2
!----------------------------------------------------------------------!
! Communication: update buffer

!     ! send left boundary
!     call MPI_SEND(p_var(2,:,:),
!    &              jmax2*kmax2,MPI_REAL,
!    &              scpu(1),0,MPI_COMM_WORLD,ierr)
!     ! send right boundary
!     call MPI_SEND(p_var(p_imax1(rank),:,:),
!    &              jmax2*kmax2,MPI_REAL,
!    &              scpu(2),1,MPI_COMM_WORLD,ierr)

!     ! recv right boundary at left buffer
!     call MPI_RECV(p_var(p_imax2(rank),:,:),
!    &              jmax2*kmax2,MPI_REAL,
!    &              rcpu(2),0,MPI_COMM_WORLD,status,ierr)
!     ! recv left boundary at left buffer
!     call MPI_RECV(p_var(1,:,:),
!    &              jmax2*kmax2,MPI_REAL,
!    &              rcpu(1),1,MPI_COMM_WORLD,status,ierr)

cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
!     end subroutine UPDATE_BUFFER_REAL
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc

!----------------------------------------------------------------------!
!      
! MPI UPDATE BUFFER REAL routine
!
! - Update buffer for a given 'real' variable
!
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine UPDATE_BUFFER_REAL (p_var)
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      use moment_dim
      use common_mpi
      implicit none
!      real,dimension(imax2(rank),p_imax2,kmax2) :: p_var
      real,dimension(imax2,p_imax2(rank),kmax2) :: p_var
      integer :: sreq1,sreq2,rreq1,rreq2
!----------------------------------------------------------------------!
! Communication: update buffer

      ! recv right boundary at left buffer
!     call MPI_IRECV(p_var(p_imax2(rank),:,:),
!    &              jmax2*kmax2,MPI_REAL,
!    &              rcpu(2),0,MPI_COMM_WORLD,sreq(1),ierr)
!     ! recv left boundary at left buffer
!     call MPI_IRECV(p_var(1,:,:),
!    &              jmax2*kmax2,MPI_REAL,
!    &              rcpu(1),1,MPI_COMM_WORLD,sreq(2),ierr)

!     ! send right boundary
!     call MPI_SEND(p_var(p_imax1(rank),:,:),
!    &              jmax2*kmax2,MPI_REAL,
!    &              scpu(2),1,MPI_COMM_WORLD,ierr)
!     ! send left boundary
!     call MPI_SEND(p_var(2,:,:),
!    &              jmax2*kmax2,MPI_REAL,
!    &              scpu(1),0,MPI_COMM_WORLD,ierr)

!     call MPI_WAITALL(2,sreq,status,ierr)


      call MPI_SENDRECV(p_var(:,2,:),jmax2*kmax2,
     .                  MPI_REAL,scpu(1),0,
     .                  p_var(:,p_imax2(rank),:),imax2*kmax2,
     .                  MPI_REAL,rcpu(2),0,
     .                  MPI_COMM_WORLD,status,ierr)

      call MPI_SENDRECV(p_var(:,p_imax1(rank),:),imax2*kmax2,
     .                  MPI_REAL,scpu(2),1,
     .                  p_var(:,1,:),imax2*kmax2,
     .                  MPI_REAL,rcpu(1),1,
     .                  MPI_COMM_WORLD,status,ierr)

cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      end subroutine UPDATE_BUFFER_REAL
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc


!----------------------------------------------------------------------!
!      
! MPI UPDATE BUFFER INTEGER routine
!
! - Update buffer for a given 'integer' variable
!
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine UPDATE_BUFFER_INTEGER (p_var)
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      use moment_dim
      use common_mpi
      implicit none
!      integer,dimension(p_imax2(rank),jmax2,kmax2) :: p_var
      integer,dimension(imax2,p_imax2(rank),kmax2) :: p_var
      integer :: sreq1,sreq2,rreq1,rreq2
      real :: sum1
!----------------------------------------------------------------------!
! Communication: update buffer

      call MPI_SENDRECV(p_var(            :,2,:),imax2*kmax2,
     .                  MPI_INTEGER,scpu(1),0,
     .                  p_var(:,p_imax2(rank),:),imax2*kmax2,
     .                  MPI_INTEGER,rcpu(2),0,
     .                  MPI_COMM_WORLD,status,ierr)

      call MPI_SENDRECV(p_var(:,p_imax1(rank),:),imax2*kmax2,
     .                  MPI_INTEGER,scpu(2),1,
     .                  p_var(            :,1,:),imax2*kmax2,
     .                  MPI_INTEGER,rcpu(1),1,
     .                  MPI_COMM_WORLD,status,ierr)

      ! send left boundary
!     call MPI_SEND(p_var(2,:,:),
!    &              jmax2*kmax2,MPI_INTEGER4,
!    &              scpu(1),0,MPI_COMM_WORLD,ierr)
!     ! send right boundary
!     call MPI_SEND(p_var(p_imax1(rank),:,:),
!    &              jmax2*kmax2,MPI_REAL4,
!    &              scpu(2),1,MPI_COMM_WORLD,ierr)
!
!
!     ! recv right boundary at left buffer
!     call MPI_RECV(p_var(p_imax2(rank),:,:),
!    &              jmax2*kmax2,MPI_INTEGER4,
!    &              rcpu(2),0,MPI_COMM_WORLD,status,ierr)
!     ! recv left boundary at left buffer
!     call MPI_RECV(p_var(1,:,:),
!    &              jmax2*kmax2,MPI_INTEGER4,
!    &              rcpu(1),1,MPI_COMM_WORLD,status,ierr)

!-----------------------------------------------------------!

      ! send left boundary
!     call MPI_ISEND(p_var(2,:,:),
!    &              jmax2*kmax2,MPI_INTEGER,
!    &              scpu(1),0,MPI_COMM_WORLD,sreq(1),ierr)
!     ! send right boundary
!     call MPI_ISEND(p_var(p_imax1(rank),:,:),
!    &              jmax2*kmax2,MPI_INTEGER,
!    &              scpu(2),1,MPI_COMM_WORLD,sreq(2),ierr)
!

!     call MPI_WAITALL(2,sreq,status,ierr)

!     ! recv right boundary at left buffer
!     call MPI_IRECV(p_var(p_imax2(rank),:,:),
!    &              jmax2*kmax2,MPI_INTEGER,
!    &              rcpu(2),0,MPI_COMM_WORLD,rreq1,ierr)
!     ! recv left boundary at left buffer
!     call MPI_IRECV(p_var(1,:,:),
!    &              jmax2*kmax2,MPI_INTEGER,
!    &              rcpu(1),1,MPI_COMM_WORLD,rreq2,ierr)


!     ! recv right boundary at left buffer
!     call MPI_RECV(p_var(p_imax2(rank),:,:),
!    &              jmax2*kmax2,MPI_INTEGER,
!    &              rcpu(2),0,MPI_COMM_WORLD,status,ierr)
!     ! recv left boundary at left buffer
!     call MPI_RECV(p_var(1,:,:),
!    &              jmax2*kmax2,MPI_INTEGER,
!    &              rcpu(1),1,MPI_COMM_WORLD,status,ierr)


!     call MPI_WAIT(sreq1,status,ierr)
!     call MPI_WAIT(sreq2,status,ierr)
!     call MPI_WAIT(rreq1,status,ierr)
!     call MPI_WAIT(rreq2,status,ierr)

cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      end subroutine UPDATE_BUFFER_INTEGER
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc


!----------------------------------------------------------------------!
!      
! MPI SEND & RECV 'MASTER to WORKER' or 'WORKER to MASTER'
!
! 1. isign(+1) : Master (global) -> WORKER (decomposed)
!    (Scattering the global array in MASTER
!         to the decomposed array in WORKER)
!
! 2. isign(-1) : Master (global) <- WORKER (decomposed)
!    (Gathering the decomposed array in WORKER
!                to the global array in MASTER )      
!               
!      
! only used for 'real' variable
!      
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine SENDRECV_MASTER_WORKER (isign,var,p_var) 
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      use moment_dim
      use common_mpi
      implicit none
      integer :: i,j,k,n,isign
      real,dimension(  imax2      ,jmax2,kmax2) :: var
!      real,dimension(p_imax2(rank),jmax2,kmax2) :: p_var
      real,dimension(imax2,p_imax2(rank),kmax2) :: p_var
!----------------------------------------------------------------------!


! isign (+1) : Scattering (MASTER -> WORKER) --------------------------! 
      if ( isign == +1 ) then

      if ( rank == master ) then ! MASTER
        do n = 1,nworker-1
          is = p_xloc_s(n) ; ie = p_xloc_e(n)
          call MPI_SEND(var(:,is:ie,:),
     &                  p_imax(n)*imax2*kmax2,MPI_REAL4,
     &                  n,0,MPI_COMM_WORLD,ierr)
        end do

          is = p_xloc_s(rank) ; ie = p_xloc_e(rank)
          p_var(:,2:p_imax1(rank),:) = var(:,is:ie,:)

      endif ! MASTER 

      if ( rank > master ) then ! WORKER
          call MPI_RECV(p_var(:,2:p_imax1(rank),:),
     &                  p_imax(rank)*imax2*kmax2,MPI_REAL4,
     &                  master,0,MPI_COMM_WORLD,status,ierr)
      endif ! WORKER 



! isign (-1) : Gathering (WORKER -> MASTER) ---------------------------!
      elseif ( isign == -1 ) then

      if ( rank > master ) then ! WORKER
          call MPI_SEND(p_var(:,2:p_imax1(rank),:),
     &                  p_imax(rank)*imax2*kmax2,MPI_REAL4,
     &                  master,0,MPI_COMM_WORLD,ierr)
      endif ! WORKER

      if ( rank == master ) then ! MASTER
        do n = 1,nworker-1
          is = p_xloc_s(n) ; ie = p_xloc_e(n)
          call MPI_RECV(var(:,is:ie,:),
     &                  p_imax(n)*imax2*kmax2,MPI_REAL4,
     &                  n,0,MPI_COMM_WORLD,status,ierr)
        end do

          is = p_xloc_s(0) ; ie = p_xloc_e(0)
          var(:,is:ie,:) = p_var(:,2:p_imax1(rank),:)

      endif ! MASTER


      endif ! isign

cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      end subroutine SENDRECV_MASTER_WORKER
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc


************************************************************************
* END of MPI related SUBROUTINEs ***************************************
************************************************************************




cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine grids
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  generate the grid system (nonuniform)
      use moment_dim

c  cell size

      do 100 i=1,imax2
      dx(i) = xint
  100 continue
      dx(1)     = 0.
      dx(imax2) = 0.

      do 120 j=1,jmax2
      dy(j) = yint
  120 continue
      dy(1)     = 0.
      dy(jmax2) = 0.

      do 140 k=1,kmax2
        dz(k) = zint
  140 continue
      dz(1)     = 0.
      dz(kmax2) = 0.

c position of each cell
      px(1) = 0.
      px(2) = 0.5*dx(2)
      do 160 i=3,imax1
  160 px(i) = px(i-1)+(dx(i-1)+dx(i))/2.
      px(imax2) = px(imax1)+0.5*dx(imax1)

      py(1) = 0.
      py(2) = 0.5*dy(2)
      do 180 j=3,jmax1
  180 py(j) = py(j-1)+(dy(j-1)+dy(j))/2.
      py(jmax2) = py(jmax1)+0.5*dy(jmax1)

      pz(1) = 0.
      pz(2) = 0.5*dz(2)
      do 200 k=3,kmax1
  200 pz(k) = pz(k-1)+(dz(k-1)+dz(k))/2.
      pz(kmax2) = pz(kmax1)+0.5*dz(kmax1)

      do 220 k=1,kmax1
      delz(k) = pz(k+1)-pz(k)
  220 continue

      do 240 j=1,jmax1
      dely(j) = py(j+1)-py(j)
  240 continue

      do 260 i=1,imax1
      delx(i) = px(i+1)-px(i)
  260 continue

      do 311 i=1,imax2
      print*, i, dx(i),px(i)
  311 continue

      do 312 j=1,jmax2
      print*, j, dy(j),py(j)
  312 continue

      do 313 k=1,kmax2
      print*, k, dz(k), pz(k)
  313 continue

      return
      end



cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine start
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      use moment_dim
cccccccccccccccccccc
c read WRF inflow
cccccccccccccccccccc
      do 110 k=1,kmax2
      do 110 j=1,jmax2 !! add
      do 110 i=1,imax2 !! add


      read(7,*) uin(i,j,k) !! add,change HJ original part
      read(8,*) vin(i,j,k) !! add,change HJ original part
      read(9,*) tmpin(i,j,k) !! add,change JH original part
      cdrag(i,j,k) = 0.2 !! HJ tree
  110 continue
      read(21,*) ((dleaf(i,j,1),i=1,imax2),j=jmax2,1,-1) !!HJ tree
      read(22,*) ((tfrac(i,j,1),i=1,imax2),j=jmax2,1,-1) !! HJ tree


 1001 format(f12.6) !! add
        print*, 'uin,   vin,   tmpin'
      do k=1,kmax2
        print*, uin(1,1,k), vin(1,1,k), tmpin(1,1,k)
      end do


      do 111 k=1,kmax2
      do 111 j=1,jmax2
      do 111 i=1,imax2
       tair(i,j,k)=tmpin(i,j,k) !-273.15 !! add,change
       ttsurface(i,j,k)=20.           !! add,change
  111 continue

!       ttsurface(i,j,k)=tsurfin
!  112 continue

!akoh       
      uu  = 0.
      uuo = 0.
      vv  = 0.
      vvo = 0.
      ww  = 0.
      wwo = 0.
      co  = 0.
      coo = 0.
      po  = 0.
      pdot = 0.
      EE  = 0.
      EEo = 0.
      DD  = 0.
      DDo = 0.
      vis = visl
!      tt = tair + 273.15
!      tto = tair +273.15
!      ref = tair +273.15
      

      do 120 k=1,kmax2
      do 120 j=1,jmax2
      do 120 i=1,imax2
      ref(i,j,k) = tair(i,j,k) + 273.15 
      tt(i,j,k) = tair(i,j,k) + 273.15
      tto(i,j,k) = tair(i,j,k) + 273.15
  120 continue

C Insert WRF Inflow to CFD
c    define influx strength

      BD = pz(kmax2)*1.1

      ustar=(sqrt(uin(1,1,10)**2+vin(1,1,10)**2)*tkapa)
     .       /alog(pz(10)/0.05)

      do 145 k=1,kmax2
      zdum = pz(k)-pz(1)
      do 145 j=1,jmax2
      do 145 i=1,imax2
       if(ija(i,j,k).ne.0) then
       uu(i,j,k)  = uin(i,j,k)  
       uuo(i,j,k) = uin(i,j,k)  
       endif

       if(ijb(i,j,k).ne.0) then
       vv(i,j,k)  = vin(i,j,k)  
       vvo(i,j,k) = vin(i,j,k)  
       endif

       if (ijc(i,j,k).ne.0) then
           ww(i,j,k) = 0.
           wwo(i,j,k) = 0.

           tt(i,j,k)  = tair(i,j,k)+273.15
           tto(i,j,k) = tair(i,j,k)+273.15
       end if


      if(ijc(i,j,k).ne.0) then
           EE(i,j,k) = ustar**2*(1.-zdum/BD)**2/cu**0.5
           EEo(i,j,k) = ustar**2*(1.-zdum/BD)**2/cu**0.5
        if (EE(i,j,k).lt.1.e-10 .or. EEo(i,j,k).lt.1.e-10) then
            EE(i,j,k)=1.e-10
            EEo(i,j,k)=1.e-10
        end if

        DD(i,j,k) = ustar**3/(tkapa*(zdum+z0))
        DDo(i,j,k) = ustar**3/(tkapa*(zdum+z0))
        vis(i,j,k) = cu*EE(i,j,k)**2/DD(i,j,k)+visl
      endif
 
  145 continue

      do 311 k=1,kmax2
      do 311 j=1,jmax2
      do 311 i=1,imax2

      pi=atan(1.)*4.

      if (vv(i,j,k).gt.0.) then
      dir(i,j,k)=((180./pi)*atan(uu(i,j,k)/vv(i,j,k)))+180.
      else if (uu(i,j,k).lt.0. .and. vv(i,j,k).lt.0.) then
      dir(i,j,k)=((180./pi)*atan(uu(i,j,k)/vv(i,j,k)))+0.
      else if (uu(i,j,k).gt.0. .and. vv(i,j,k).lt.0.) then
      dir(i,j,k)=((180./pi)*atan(uu(i,j,k)/vv(i,j,k)))+360.
      else
      dir(i,j,k)=0.
      end if
      ws(i,j,k) = ((uu(i,j,k)**2.)+(vv(i,j,k)**2.))**(1./2.)

  311 continue


       print *, "ustar = ", ustar

       print *, "    "
       print *, "========== After height correction =========="
       print *, 'k  ', 'pz   ', "uu   ", "vv   "
     ., "tmp   ","EE   ","DD   ","vis   "

       do 2010 k = 1,kmax2

        write(*,777) k,pz(k),uu(100,jmax/2,k),vv(100,jmax/2,k),
     .                       tt(100,jmax/2,k),EE(100,jmax/2,k),
     .                       DD(100,jmax/2,k),vis(100,jmax/2,k)
 2010 continue

  777 format (I3.3,1x,f15.5,2f10.6,f14.6,2f10.6,f14.6,f10.6,f14.6)



      if(ither.eq.1) then

      do 200 k=2,kmax1
      do 200 j=2,jmax1
      do 200 i=2,imax1

      if(iloca1.eq.1) then
      if((ijc(i,j,k).ne.0).and.(ijc(i-1,j,k).eq.0)) then
      tt(i-1,j,k) = ttsurface(i-1,j,k) + 273.15
      endif
      endif

      if(iloca2.eq.1) then
      if((ijc(i,j,k).ne.0).and.(ijc(i+1,j,k).eq.0)) then
      tt(i+1,j,k) = ttsurface(i+1,j,k) + 273.15
      endif
      endif

      if(iloca3.eq.1) then
      if((ijc(i,j,k).ne.0).and.(ijc(i,j-1,k).eq.0)) then
      tt(i,j-1,k) = ttsurface(i,j-1,k) + 273.15
      endif
      endif

      if(iloca4.eq.1) then
      if((ijc(i,j,k).ne.0).and.(ijc(i,j+1,k).eq.0)) then
      tt(i,j+1,k) = ttsurface(i,j+1,k) + 273.15
      endif
      endif

      if(iloca5.eq.1) then
      if((ijc(i,j,k).ne.0).and.(ijc(i,j,k-1).eq.0)) then
      tt(i,j,k-1) = ttsurface(i,j,k-1) + 273.15
      endif
      endif

      if(iloca6.eq.1) then
      if((ijc(i,j,2).ne.0).and.(ijc(i,j,1).eq.0)) then
      tt(i,j,1) = ttsurface(i,j,1) + 273.15
      endif
      endif

      if(iloca7.eq.1) then
      if((ijc(i,j,k).ne.0).and.(ijc(i,j,k+1).eq.0)) then
      tt(i,j,k+1) = ttsurface(i,j,k+1) + 273.15
      endif
      endif

  200 continue

      endif

      return
      end


cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine inflow_condition
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      use moment_dim
      use common_mpi

      do 150 k=2,kmax2
      do 150 j=p_is_g(rank),p_ie_g(rank) 
      do 150 i=1,imax2
         if ((p_uu(i,j,k).gt.0).and.(p_vv(i,j,k).gt.0)) then

           infw(i,j,k) = 1
           infe(i,j,k) = 2

           infn(i,j,k) = 2
           infs(i,j,k) = 1


         else if((p_uu(i,j,k).gt.0).and.(p_vv(i,j,k).lt.0)) then

           infw(i,j,k) = 1
           infe(i,j,k) = 2

           infn(i,j,k) = 1
           infs(i,j,k) = 2
          
         else if((p_uu(i,j,k).lt.0).and.(p_vv(i,j,k).lt.0)) then

           infw(i,j,k) = 2
           infe(i,j,k) = 1

           infn(i,j,k) = 1
           infs(i,j,k) = 2

         else if((p_uu(i,j,k).lt.0).and.(p_vv(i,j,k).gt.0)) then

           infw(i,j,k) = 2
           infe(i,j,k) = 1

           infn(i,j,k) = 2
           infs(i,j,k) = 1

         else if((p_uu(i,j,k).gt.0).and.(p_vv(i,j,k).eq.0)) then

           infw(i,j,k) = 1
           infe(i,j,k) = 2

           infn(i,j,k) = 0
           infs(i,j,k) = 0

         else if((p_uu(i,j,k).eq.0).and.(p_vv(i,j,k).lt.0)) then

           infw(i,j,k) = 0
           infe(i,j,k) = 0

           infn(i,j,k) = 1
           infs(i,j,k) = 2

         else if((p_uu(i,j,k).lt.0).and.(p_vv(i,j,k).eq.0)) then

           infw(i,j,k) = 2
           infe(i,j,k) = 1

           infn(i,j,k) = 0
           infs(i,j,k) = 0

         else if((p_uu(i,j,k).eq.0).and.(p_vv(i,j,k).gt.0)) then

           infw(i,j,k) = 0
           infe(i,j,k) = 0

           infn(i,j,k) = 2
           infs(i,j,k) = 1

         end if

  150 continue

      call UPDATE_BUFFER_INTEGER(infe)         
      call UPDATE_BUFFER_INTEGER(infw)         
      call UPDATE_BUFFER_INTEGER(infs)         
      call UPDATE_BUFFER_INTEGER(infn)         

      return
      end   

cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_coefu         
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  calculate the coefficients of the finite difference
c  equation for the x-momentum equation
!----------------------------------------------------------------------!      
      use moment_dim
      use common_mpi
!----------------------------------------------------------------------!      
     
       p_al(:,:,:) = 0.
       p_ah(:,:,:) = 0.
       p_as(:,:,:) = 0.
       p_an(:,:,:) = 0.
       p_aw(:,:,:) = 0.
       p_ae(:,:,:) = 0.
      p_spu(:,:,:) = 0.

      do 200 k=2,kmax1
      do 200 j=p_is_o(rank),p_ie_o(rank) ! 2~jmax1
      do 200 i=2,imax ! 2~imax 

      if(p_ija(i,j,k).eq.0) go to 200

      if(p_ija(i,j,k-1).eq.0) then
        dlzm = 0.5*dz(k)
      else
        dlzm = delz(k-1)
      end if
 
      if(p_ija(i,j,k+1).eq.0) then
        dlzp = 0.5*dz(k)
      else
        dlzp = delz(k)
      end if
 
      if(p_ija(i,j-1,k).eq.0) then
        dlym = 0.5*p_dy(j)
      else
        dlym = p_dely(j-1)
      end if
     
      if(p_ija(i,j+1,k).eq.0) then
        dlyp = 0.5*p_dy(j)
      else
        dlyp = p_dely(j)
      end if

!-----      

      dlvis = (dz(k-1)*(dx(i+1)*p_vis(i,  j,k  )
     .                 +dx(i  )*p_vis(i+1,j,k  ))
     .        +dz(k  )*(dx(i+1)*p_vis(i,  j,k-1)
     .                 +dx(i  )*p_vis(i+1,j,k-1)))
     .       /((dx(i)+dx(i+1))*(dz(k)+dz(k-1)))
      dl    = dlvis / dlzm
      den   = (p_dena(i+1,j,k  )+p_dena(i,j,k  )
     .        +p_dena(i+1,j,k-1)+p_dena(i,j,k-1))/4.
      fz    = den*( dx(i+1)*p_ww(i  ,j,k-1)
     .             +dx(i  )*p_ww(i+1,j,k-1)) /(dx(i)+dx(i+1))
      p_al(i,j,k) = delx(i)*p_dy(j)
     .            *(dl*amax1(0.,(1.-0.1*abs(fz)/dl)**5)+amax1(fz,0.))
     .            *p_afac(i,j,k)

!-----      

      dsvis =  (p_dy(j-1)*(dx(i+1)*p_vis(i  ,j  ,k)
     .                  +dx(i  )*p_vis(i+1,j  ,k))
     .         +p_dy(j  )*(dx(i+1)*p_vis(i  ,j-1,k)
     .                  +dx(i  )*p_vis(i+1,j-1,k)))
     .       /((dx(i)+dx(i+1))*(p_dy(j-1)+p_dy(j)))
      ds    = dsvis/dlym
      den   = (p_dena(i+1,j  ,k)+p_dena(i,j  ,k)
     .        +p_dena(i+1,j-1,k)+p_dena(i,j-1,k))/4.
      fy    = den*(dx(i+1)*p_vv(i  ,j-1,k)
     .            +dx(i  )*p_vv(i+1,j-1,k)) / (dx(i)+dx(i+1))
      p_as(i,j,k) = delx(i)*dz(k)
     &            *(ds*amax1(0.,(1.-0.1*abs(fy)/ds)**5)+amax1(fy,0.))
     &            *p_afab(i,j-1,k)

!-----      

      dw  = p_vis(i,j,k)/dx(i)
      den = p_dena(i,j,k)
      fx  = den*(p_uu(i-1,j,k)+p_uu(i,j,k))/2.
      p_aw(i,j,k) = p_dy(j)*dz(k)
     .            *(dw*amax1(0.,(1.-0.1*abs(fx)/dw)**5)+amax1(fx,0.))
     .            *p_afaa(i,j,k)

!-----      

      de  =  p_vis(i+1,j,k) / dx(i+1)
      den = p_dena(i+1,j,k)
      fx  = den*(p_uu(i,j,k)+p_uu(i+1,j,k))/2.
      p_ae(i,j,k) = p_dy(j)*dz(k)
     .            *(de*amax1(0.,(1.-0.1*abs(fx)/de)**5)+amax1(0.,-fx))
     .            *p_afaa(i+1,j,k)

!-----      

      dnvis = (p_dy(j  )*(dx(i+1)*p_vis(i  ,j+1,k)
     .                 +dx(i  )*p_vis(i+1,j+1,k))
     .        +p_dy(j+1)*(dx(i+1)*p_vis(i  ,j  ,k)
     .                 +dx(i  )*p_vis(i+1,j  ,k)))
     .      /((dx(i)+dx(i+1))*(p_dy(j)+p_dy(j+1)))
      dn    = dnvis/dlyp
      den   = (p_dena(i+1,j  ,k)+p_dena(i,j  ,k)
     .        +p_dena(i+1,j+1,k)+p_dena(i,j+1,k))/4.
      fy    = den*(dx(i+1)*p_vv(i  ,j,k)
     .            +dx(i  )*p_vv(i+1,j,k)) / (dx(i)+dx(i+1))
      p_an(i,j,k) = delx(i)*dz(k)
     .            *(dn*amax1(0.,(1.-0.1*abs(fy)/dn)**5)+amax1(0.,-fy))
     .            *p_afab(i,j,k)

!-----      

      dhvis = (dz(k  )*(dx(i+1)*p_vis(i  ,j,k+1)
     .                 +dx(i  )*p_vis(i+1,j,k+1))
     .        +dz(k+1)*(dx(i+1)*p_vis(i  ,j,k  )
     .                 +dx(i  )*p_vis(i+1,j,k  )))
     .       /((dx(i)+dx(i+1))*(dz(k)+dz(k+1)))

      dh    = dhvis/dlzp

      den   = (p_dena(i+1,j,k  )+p_dena(i,j,k  )
     .        +p_dena(i+1,j,k+1)+p_dena(i,j,k+1))/4.

      fz    = den*(dx(i+1)*p_ww(i  ,j,k) 
     .            +dx(i  )*p_ww(i+1,j,k)) / (dx(i)+dx(i+1))

      p_ah(i,j,k) = delx(i)*p_dy(j)
     .            *(dh*amax1(0.,(1.-0.1*abs(fz)/dh)**5)+amax1(0.,-fz))
     .            *p_afac(i,j,k+1)

!-----      

      p_apx(i,j,k) = (p_denao(i,j,k)+p_denao(i+1,j,k))
     .              *delx(i)*p_dy(j)*dz(k)*p_afav(i,j,k)/(2.*delt)
     .              +p_ae(i,j,k)+p_aw(i,j,k)+p_an(i,j,k)
     .              +p_as(i,j,k)+p_ah(i,j,k)+p_al(i,j,k)

!-----      
      soru1 = -2./3.*(p_EE(i+1,j,k)-p_EE(i,j,k))/delx(i)

      soru2 = (p_vis(i+1,j,k)*(p_uu(i+1,j,k)-p_uu(i  ,j,k))/dx(i+1)
     .        -p_vis(i  ,j,k)*(p_uu(i  ,j,k)-p_uu(i-1,j,k))/dx(i  ))
     .       /delx(i)

      soru3 = (dnvis*(p_vv(i+1,j  ,k)-p_vv(i,j  ,k))/delx(i)
     .        -dsvis*(p_vv(i+1,j-1,k)-p_vv(i,j-1,k))/delx(i))/p_dy(j)

      soru4 = (dhvis*(p_ww(i+1,j,k  )-p_ww(i,j,k  ))/delx(i)
     .        -dlvis*(p_ww(i+1,j,k-1)-p_ww(i,j,k-1))/delx(i))/dz(k)

      p_s(i,j,k) = (p_denao(i,j,k)+p_denao(i+1,j,k))*p_uuo(i,j,k)
     .             *delx(i)*p_dy(j)*dz(k)*p_afav(i,j,k)/(2.*delt)
     .        -p_dy(j)*dz(k)*p_afsa(i+1,j,k)*(p_po(i+1,j,k)-p_po(i,j,k))
     .            +(p_dena(i,j,k)+p_dena(i+1,j,k))/2.
     .            *(soru1+soru2+soru3+soru4)*delx(i)*p_dy(j)*dz(k)
     .            *p_afav(i,j,k)
!-----      
     
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c Drag force by trees
      IF(itree .eq. 1) then !HJ tree
      IF(p_ita(i,j,k) .eq. 0) then
      tv1 = (dx(i+1)*p_vv(i,j-1,k)+dx(i)*p_vv(i+1,j-1,k))
     .     /(dx(i)+dx(i+1))
      tv2 = (dx(i+1)*p_vv(i,j,k)+dx(i)*p_vv(i+1,j,k))
     .     /(dx(i)+dx(i+1))

      tw1 = (dx(i+1)*p_ww(i,j,k-1)+dx(i)*p_ww(i+1,j,k-1))
     .     /(dx(i)+dx(i+1))
      tw2 = (dx(i+1)*p_ww(i,j,k)+dx(i)*p_ww(i+1,j,k))
     .     /(dx(i)+dx(i+1))

      vel = sqrt(p_uuo(i,j,k)**2.+0.25*(tv1+tv2)**2.+0.25*(tw1+tw2)**2.)

      p_spx(i,j,k) = -0.5*(p_dena(i,j,k)+p_dena(i+1,j,k))
     .             *p_cdrag(i,j,k)*p_tfrac(i,j,1)*p_dleaf(i,j,1)*vel

      p_apx(i,j,k) = p_apx(i,j,k) - p_spx(i,j,k)

      endif
      endif
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
 
  200 continue

c  implement boundary conditions
c  at the lower boundary

      do 220 j=p_is_o(rank),p_ie_o(rank)
      do 220 i=2,imax

      if(p_ija(i,j,2).ne.0) then

      eavr = (dx(i+1)*p_EE(i,j,2)+dx(i)*p_EE(i+1,j,2))
     .      /(dx(i)+dx(i+1))
      yplus = 0.5*dz(2)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,2)+p_dena(i+1,j,2))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*dz(2))
      endif

      p_spu(i,j,2) = utau*delx(i)*p_dy(j)*(1.-p_afac(i,j,2))
      p_apx(i,j,2) = p_apx(i,j,2) - p_spu(i,j,2)
       p_al(i,j,2) = 0.
      endif

  220 continue

c  at the upper boundary (shear-free flow)
      do 240 j=p_is_o(rank),p_ie_o(rank)
      do 240 i=2,imax

      p_apx(i,j,kmax1) = p_apx(i,j,kmax1)-p_ah(i,j,kmax1)
         p_ah(i,j,kmax1) = 0.
  240 continue

c  at the top of the buildings 
      do 260 k=3,kmax1
      do 260 j=p_is_o(rank),p_ie_o(rank)
      do 260 i=2,imax

      if((p_ija(i,j,k).eq.1).and.(p_ija(i,j,k-1).ne.1)) then

      eavr = (dx(i+1)*p_EE(i,j,k)+dx(i)*p_EE(i+1,j,k))
     .      /(dx(i)+dx(i+1))
      yplus = 0.5*dz(k)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i+1,j,k))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*dz(k))
      endif

      p_spu(i,j,k) = utau*delx(i)*p_dy(j)*(1.-p_afac(i,j,k))
      p_apx(i,j,k) = p_apx(i,j,k) - p_spu(i,j,k)
      endif

      if((p_ija(i,j,k).eq.1).and.(p_ija(i,j,k+1).ne.1)) then

      eavr = (dx(i+1)*p_EE(i,j,k)+dx(i)*p_EE(i+1,j,k))
     .      /(dx(i)+dx(i+1))
      yplus = 0.5*dz(k)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i+1,j,k))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*dz(k))
      endif

      p_spu(i,j,k) = utau*delx(i)*p_dy(j)*(1.-p_afac(i,j,k+1))
      p_apx(i,j,k) = p_apx(i,j,k) - p_spu(i,j,k)
      endif

      if(p_ija(i,j,k).eq.2) then

      eavr = (dx(i+1)*p_EE(i,j,k)+dx(i)*p_EE(i+1,j,k))
     .      /(dx(i)+dx(i+1))
      yplus = 0.5*dz(k)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i+1,j,k))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*dz(k))
      endif

      p_spu(i,j,k) = utau*delx(i)*p_dy(j)
     .            *abs(p_afac(i,j,k+1)-p_afac(i,j,k))
      p_apx(i,j,k) = p_apx(i,j,k) - p_spu(i,j,k)

      endif

  260 continue

c  at the building walls 
      do 280 k=2,kmax1
      do 280 j=p_is_o(rank),p_ie_o(rank)
      do 280 i=2,imax

      if(p_ija(i,j,k).eq.1) then

      if(p_ija(i-1,j,k).eq.0) p_aw(i,j,k)=0.
      if(p_ija(i+1,j,k).eq.0) p_ae(i,j,k)=0.

      if((1.-p_afab(i,j-1,k)).gt.1.e-6) then

      eavr = (dx(i+1)*p_EE(i,j,k)+dx(i)*p_EE(i+1,j,k))
     .      /(dx(i)+dx(i+1))
      yplus = 0.5*p_dy(j)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i+1,j,k))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*p_dy(j))
      endif

      p_spu(i,j,k) = utau*delx(i)*dz(k)*(1.-p_afab(i,j-1,k))
      p_apx(i,j,k) = p_apx(i,j,k) - p_spu(i,j,k)
      endif

      if((1.-p_afab(i,j,k)).gt.1.e-6) then

      eavr = (dx(i+1)*p_EE(i,j,k)+dx(i)*p_EE(i+1,j,k))
     .      /(dx(i)+dx(i+1))
      yplus = 0.5*p_dy(j)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i+1,j,k))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*p_dy(j))
      endif

      p_spu(i,j,k) = utau*delx(i)*dz(k)*(1.-p_afab(i,j,k))
      p_apx(i,j,k) = p_apx(i,j,k) - p_spu(i,j,k)
      endif
      end if

      if(p_ija(i,j,k).eq.2) then

      eavr = (dx(i+1)*p_EE(i,j,k)+dx(i)*p_EE(i+1,j,k))
     .      /(dx(i)+dx(i+1))
      yplus = 0.5*p_dy(j)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i+1,j,k))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*p_dy(j))
      endif

      p_spu(i,j,k) = utau*delx(i)*dz(k)
     .            *abs(p_afab(i,j,k)-p_afab(i,j-1,k))
      p_apx(i,j,k) = p_apx(i,j,k) - p_spu(i,j,k)
      endif

  280 continue

c  at the horizontal boundaries
c  x = 0
c  shear-free or outflow conditions?


!      is_u = p_is_u(rank) ! = 2 

      do 320 k=2,kmax1
      do 320 j=p_is_o(rank),p_ie_o(rank)
      if((infw(1,j,k).eq.0).or.(infw(1,j,k).eq.2)) then
      if(p_ija(2,j,k).ne.0) then
      p_apx(2,j,k) = p_apx(2,j,k)-p_aw(2,j,k)
      p_aw(2,j,k)  = 0.
      end if
      end if
  320 continue
c  inflow conditions?

      do 340 k=2,kmax1
      do 340 j=p_is_o(rank),p_ie_o(rank)
      if(infw(1,j,k).eq.1) then
      if(p_ija(2,j,k).ne.0) then
      p_s(2,j,k)  = p_s(2,j,k)+p_uu(1,j,k)*p_aw(2,j,k)
      p_aw(2,j,k) = 0.            !    is    !
      end if
      end if
  340 continue




c  x = xmax  
c  shear-free or outflow conditions?

!      ie_u = p_ie_u(rank) ! = imax
!      ie1  = p_ie_g(rank) ! = imax2
      do 360 k=2,kmax1
      do 360 j=p_is_o(rank),p_ie_o(rank)
      if((infe(imax1,j,k).eq.0).or.(infe(imax1,j,k).eq.2)) then
      if(p_ija(imax,j,k).ne.0) then
      p_apx(imax,j,k) = p_apx(imax,j,k)-p_ae(imax,j,k)
      p_ae(imax,j,k)  = 0.
      end if
      end if
  360 continue
c  inflow conditions?

      do 380 k=2,kmax1
      do 380 j=p_is_o(rank),p_ie_o(rank)
      if(infe(imax1,j,k).eq.1) then
      if(p_ija(imax,j,k).ne.0) then
      p_s(imax,j,k)  = p_s(imax,j,k)+p_uu(imax1,j,k)*p_ae(imax,j,k)
      p_ae(imax,j,k) = 0.            !    ie    !
      end if
      end if
  380 continue



      if ( rank == 0 ) then ! WORKER 1 only for x = 0 ##################
      is  = p_is_o(rank)    ! = 2
      iss = 1               ! = 1
c  y = 0
c  shear-free or outflow conditions?
      do 420 k=2,kmax1
      do 420 i=2,imax
      if((infs(i,iss,k).eq.0).or.(infs(i,iss,k).eq.2)) then
      if(p_ija(i,is,k).ne.0) then
      p_apx(i,is,k) = p_apx(i,is,k)-p_as(i,is,k)
      p_as(i,is,k)  = 0.
      end if
      end if
  420 continue
c  inflow conditions?
      do 440 k=2,kmax1
      do 440 i=2,imax
      if(infs(i,iss,k).eq.1) then
      if(p_ija(i,is,k).ne.0) then
      p_s(i,is,k)  = p_s(i,is,k)+p_uu(i,iss,k)*p_as(i,is,k)
      p_as(i,is,k) = 0.
      end if
      end if
  440 continue
      end if


      if ( rank == nworker-1 ) then ! WORKER nworker only for x = xmax ###
      ie  = p_ie_o(rank)  ! = imax  ##jmax1
      iee = p_imax1(rank) ! = imax1 ##jmax2
c  y = ymax
c  shear-free or outflow conditions?
      do 460 k=2,kmax1
      do 460 i=2,imax
      if((infn(i,iee,k).eq.0).or.(infn(i,iee,k).eq.2)) then
      if(p_ija(i,ie,k).ne.0) then
      p_apx(i,ie,k) = p_apx(i,ie,k)-p_an(i,ie,k)
      p_an(i,ie,k)  = 0.
      end if
      end if
  460 continue
c  inflow conditions?
      do 480 k=2,kmax1
      do 480 i=2,imax ! 2~imax
      if(infn(i,iee,k).eq.1) then
      if(p_ija(i,ie,k).ne.0) then
      p_s(i,ie,k)  = p_s(i,ie,k)+p_uu(i,iee,k)*p_an(i,ie,k)
      p_an(i,ie,k) = 0.
      end if
      end if
  480 continue
      end if

      return
      end


cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_coefv        
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  calculate the coefficients of the finite difference
c  equation for the y-momentum equation
!----------------------------------------------------------------------!      
      use moment_dim
      use common_mpi
!----------------------------------------------------------------------!      


      p_al(:,:,:) = 0.
      p_ah(:,:,:) = 0.
      p_as(:,:,:) = 0.
      p_an(:,:,:) = 0.
      p_aw(:,:,:) = 0.
      p_ae(:,:,:) = 0.
      p_spv(:,:,:) = 0.

      do 200 k=2,kmax1
      do 200 j=p_is_u(rank),p_ie_u(rank)
      do 200 i=2,imax1

      if(p_ijb(i,j,k).eq.0) go to 200

      if(p_ijb(i,j,k-1).eq.0) then
      dlzm = 0.5*dz(k)
      else
      dlzm = delz(k-1)
      end if
     
      if(p_ijb(i,j,k+1).eq.0) then
      dlzp = 0.5*dz(k)
      else
      dlzp = delz(k)
      end if
     
      if(p_ijb(i-1,j,k).eq.0) then
      dlxm = 0.5*dx(i)
      else
      dlxm = delx(i-1)
      end if
     
      if(p_ijb(i+1,j,k).eq.0) then
      dlxp = 0.5*dx(i)
      else
      dlxp = delx(i)
      end if

      dlvis = (dz(k-1)*(p_dy(j+1)*p_vis(i,j,k)+p_dy(j)*p_vis(i,j+1,k))
     .     + dz(k)*(p_dy(j+1)*p_vis(i,j,k-1)+p_dy(j)*p_vis(i,j+1,k-1)))
     .     /((p_dy(j)+p_dy(j+1))*(dz(k)+dz(k-1)))

      dl  = dlvis/dlzm
      den = (p_dena(i,j,k-1)+p_dena(i,j+1,k-1)
     .      +p_dena(i,j,k  )+p_dena(i,j+1,k  ))/4.
      fz  = den*(p_dy(j+1)*p_ww(i,j,k-1)+p_dy(j)*p_ww(i,j+1,k-1))
     .     /(p_dy(j)+p_dy(j+1))
      p_al(i,j,k) = dx(i)*p_dely(j)
     .            *(dl*amax1(0.,(1.-0.1*abs(fz)/dl)**5)+amax1(fz,0.))
     .            *p_afbc(i,j,k)

      ds  = p_vis(i,j,k)/p_dy(j)
      den = (p_dena(i,j,k)+p_dena(i,j,k)+p_dena(i,j,k)+p_dena(i,j,k))/4.
      fy  = den*(p_vv(i,j-1,k)+p_vv(i,j,k))/2.
      p_as(i,j,k) = dx(i)*dz(k)*(ds*amax1(0.,(1.-0.1*abs(fy)/ds)**5)+
     .  amax1(fy,0.))*p_afbb(i,j-1,k)

      dwvis =  (dx(i-1)*(p_dy(j+1)*p_vis(i,j,k)+p_dy(j)*p_vis(i,j+1,k))
     .     + dx(i)*(p_dy(j+1)*p_vis(i-1,j,k)+p_dy(j)*p_vis(i-1,j+1,k)))
     .     /((dx(i-1)+dx(i))*(p_dy(j)+p_dy(j+1)))

      dw  = dwvis/dlxm
      den = (p_dena(i-1,j,k)+p_dena(i-1,j+1,k)
     .      +p_dena(i  ,j,k)+p_dena(i  ,j+1,k))/4.
      fx  = den*(p_dy(j+1)*p_uu(i-1,j,k)+p_dy(j)*p_uu(i-1,j+1,k))
     .     /(p_dy(j)+p_dy(j+1))
      p_aw(i,j,k) = p_dely(j)*dz(k)*(dw*amax1(0.,(1.-0.1*abs(fx)/dw)**5)
     .  +amax1(fx,0.))*p_afba(i,j,k)

      devis = (dx(i)*(p_dy(j+1)*p_vis(i+1,j,k)+p_dy(j)*p_vis(i+1,j+1,k))
     .     + dx(i+1)*(p_dy(j+1)*p_vis(i,j,k)+p_dy(j)*p_vis(i,j+1,k)))
     .     /((dx(i)+dx(i+1))*(p_dy(j)+p_dy(j+1)))

      de  = devis/dlxp
      den = (p_dena(i  ,j,k)+p_dena(i  ,j+1,k)
     .      +p_dena(i+1,j,k)+p_dena(i+1,j+1,k))/4.
      fx  = den*(p_dy(j+1)*p_uu(i,j,k)+p_dy(j)*p_uu(i,j+1,k))
     .     /(p_dy(j)+p_dy(j+1))
      p_ae(i,j,k) = p_dely(j)*dz(k)*(de*amax1(0.,(1.-0.1*abs(fx)/de)**5)
     .  +amax1(0.,-fx))*p_afba(i+1,j,k)

      dn  = p_vis(i,j+1,k)/p_dy(j+1)
      den = (p_dena(i,j+1,k)+p_dena(i,j+1,k)
     .      +p_dena(i,j+1,k)+p_dena(i,j+1,k))/4.
      fy  = den*(p_vv(i,j,k)+p_vv(i,j+1,k))/2.
      p_an(i,j,k) = dx(i)*dz(k)*(dn*amax1(0.,(1.-0.1*abs(fy)/dn)**5)+
     .  amax1(0.,-fy))*p_afbb(i,j,k)

      dhvis = (dz(k)*(p_dy(j+1)*p_vis(i,j,k+1)+p_dy(j)*p_vis(i,j+1,k+1))
     .     + dz(k+1)*(p_dy(j+1)*p_vis(i,j,k)+p_dy(j)*p_vis(i,j+1,k)))
     .     /((p_dy(j)+p_dy(j+1))*(dz(k)+dz(k+1)))

      dh  = dhvis/dlzp
      den = (p_dena(i,j  ,k)+p_dena(i,j  ,k+1)
     .      +p_dena(i,j+1,k)+p_dena(i,j+1,k+1))/4.
      fz  = den*(p_dy(j+1)*p_ww(i,j,k)+p_dy(j)*p_ww(i,j+1,k))
     .     /(p_dy(j)+p_dy(j+1))
      p_ah(i,j,k) = dx(i)*p_dely(j)
     .            *(dh*amax1(0.,(1.-0.1*abs(fz)/dh)**5)+amax1(0.,-fz))
     .            *p_afbc(i,j,k+1)

      p_apy(i,j,k) = (p_denao(i,j,k)+p_denao(i,j+1,k))
     .               *dx(i)*p_dely(j)*dz(k)*p_afbv(i,j,k)/(2.*delt)
     .             +p_ae(i,j,k)+p_aw(i,j,k)+p_an(i,j,k)
     .             +p_as(i,j,k)+p_ah(i,j,k)+p_al(i,j,k) 

      sorv1 = -2./3.*(p_EE(i,j+1,k)-p_EE(i,j,k))/p_dely(j)

      sorv2 = (p_vis(i,j+1,k)*(p_vv(i,j+1,k)-p_vv(i,j,k))/p_dy(j+1)
     .     -p_vis(i,j,k)*(p_vv(i,j,k)-p_vv(i,j-1,k))/p_dy(j))/p_dely(j)

      sorv3 = (devis*(p_uu(i,j+1,k)-p_uu(i,j,k))/p_dely(j)
     .        -dwvis*(p_uu(i-1,j+1,k)-p_uu(i-1,j,k))/p_dely(j))/dx(i)

      sorv4 = (dhvis*(p_ww(i,j+1,k)-p_ww(i,j,k))/p_dely(j)
     .        -dlvis*(p_ww(i,j+1,k-1)-p_ww(i,j,k-1))/p_dely(j))/dz(k)

      p_s(i,j,k) = (p_denao(i,j,k)+p_denao(i,j+1,k))
     .             *p_vvo(i,j,k)*dx(i)*p_dely(j)*dz(k)
     .             *p_afbv(i,j,k)/(2.*delt)
     .            -dx(i)*dz(k)*(p_po(i,j+1,k)-p_po(i,j,k))*p_afsb(i,j,k)
     .           +(p_dena(i,j,k)+p_dena(i,j+1,k))/2.
     .           *(sorv1+sorv2+sorv3+sorv4)
     .           *dx(i)*p_dely(j)*dz(k)*p_afbv(i,j,k)

cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c Drag force by trees
      IF(itree .eq. 1) then !HJ tree
      IF(p_itb(i,j,k) .eq. 0 ) then
      tu1 =(dy(j+1)*p_uu(i-1,j,k)+dy(j)*p_uu(i-1,j+1,k))/(dy(j)+dy(j+1))
      tu2 =(dy(j+1)*p_uu(i,j,k)+dy(j)*p_uu(i,j+1,k))/(dy(j)+dy(j+1))

      tw1 =(dy(j+1)*p_ww(i,j,k-1)+dy(j)*p_ww(i,j+1,k-1))/(dy(j)+dy(j+1))
      tw2 =(dy(j+1)*p_ww(i,j,k)+dy(j)*p_ww(i,j+1,k))/(dy(j)+dy(j+1))

      vel =sqrt(p_vvo(i,j,k)**2.+0.25*(tu1+tu2)**2.+0.25*(tw1+tw2)**2.)
      p_spy(i,j,k) = -0.5*(p_dena(i,j,k)+p_dena(i,j+1,k))
     .             *p_cdrag(i,j,k)*p_tfrac(i,j,1)*p_dleaf(i,j,1)*vel
      p_apy(i,j,k) = p_apy(i,j,k) - p_spy(i,j,k)

      end if
      endif
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc

  200 continue

c  implement boundary conditions
c  at the lower boundary 
      do 220 j=p_is_u(rank),p_ie_u(rank)
      do 220 i=2,imax1

      if(p_ijb(i,j,2).ne.0) then
   
      eavr = (p_dy(j+1)*p_EE(i,j,2)+p_dy(j)*p_EE(i,j+1,2))
     .       /(p_dy(j)+p_dy(j+1))
      yplus = 0.5*dz(2)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,2)+p_dena(i,j+1,2))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*dz(2))
      endif

      p_spv(i,j,2) = utau*p_dely(j)*dx(i)*(1.-p_afbc(i,j,2))
      p_apy(i,j,2) = p_apy(i,j,2) - p_spv(i,j,2)
      p_al(i,j,2)=0.
      endif

  220 continue

c  at the upper boundary (shear-free flow)
      do 240 j=p_is_u(rank),p_ie_u(rank)
      do 240 i=2,imax1
      p_apy(i,j,kmax1) = p_apy(i,j,kmax1)-p_ah(i,j,kmax1)
      p_ah(i,j,kmax1)  = 0.
  240 continue

c  at the top of the buildings 
      do 260 k=3,kmax1
      do 260 j=p_is_u(rank),p_ie_u(rank)
      do 260 i=2,imax1

      if((p_ijb(i,j,k).eq.1).and.(p_ijb(i,j,k-1).ne.1)) then

      eavr = (p_dy(j+1)*p_EE(i,j,k)+p_dy(j)*p_EE(i,j+1,k))
     .       /(p_dy(j)+p_dy(j+1))
      yplus = 0.5*dz(k)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i,j+1,k))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*dz(k))
      endif

      p_spv(i,j,k) = utau*p_dely(j)*dx(i)*(1.-p_afbc(i,j,k))
      p_apy(i,j,k) = p_apy(i,j,k) - p_spv(i,j,k)
      endif

      if((p_ijb(i,j,k).eq.1).and.(p_ijb(i,j,k+1).ne.1)) then

      eavr = (p_dy(j+1)*p_EE(i,j,k)+p_dy(j)*p_EE(i,j+1,k))
     .       /(p_dy(j)+p_dy(j+1))
      yplus = 0.5*dz(k)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i,j+1,k))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*dz(k))
      endif

      p_spv(i,j,k) = utau*p_dely(j)*dx(i)*(1.-p_afbc(i,j,k+1))
      p_apy(i,j,k) = p_apy(i,j,k) - p_spv(i,j,k)
      endif

      if(p_ijb(i,j,k).eq.2) then

      eavr = (p_dy(j+1)*p_EE(i,j,k)+p_dy(j)*p_EE(i,j+1,k))
     .       /(p_dy(j)+p_dy(j+1))
      yplus = 0.5*dz(k)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i,j+1,k))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*dz(k))
      endif

      p_spv(i,j,k) = utau*p_dely(j)*dx(i)
     .            *abs(p_afbc(i,j,k+1)-p_afbc(i,j,k))
      p_apy(i,j,k) = p_apy(i,j,k) - p_spv(i,j,k)
      endif

  260 continue

c  at the building walls 
      do 280 k=2,kmax1
      do 280 j=p_is_u(rank),p_ie_u(rank)
      do 280 i=2,imax1

      if(p_ijb(i,j,k).eq.1) then

      if(p_ijb(i-1,j,k).ne.1) then

      eavr = (p_dy(j+1)*p_EE(i,j,k)+p_dy(j)*p_EE(i,j+1,k))
     .       /(p_dy(j)+p_dy(j+1))
      yplus = 0.5*dx(i)*cu**0.25*eavr**0.5/visl
 
      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i,j+1,k))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*dx(i))
      endif

      p_spv(i,j,k) = utau*p_dely(j)*dz(k)*(1.-p_afba(i,j,k))
      p_apy(i,j,k) = p_apy(i,j,k) - p_spv(i,j,k)
      endif

      if(p_ijb(i+1,j,k).ne.1) then

      eavr = (p_dy(j+1)*p_EE(i,j,k)+p_dy(j)*p_EE(i,j+1,k))
     .       /(p_dy(j)+p_dy(j+1))
      yplus = 0.5*dx(i)*cu**0.25*eavr**0.5/visl
 
      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i,j+1,k))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*dx(i))
      endif

      p_spv(i,j,k) = utau*p_dely(j)*dz(k)*(1.-p_afba(i+1,j,k))
      p_apy(i,j,k) = p_apy(i,j,k) - p_spv(i,j,k)
      endif

      if(p_ijb(i,j-1,k).eq.0) p_as(i,j,k)=0.
      if(p_ijb(i,j+1,k).eq.0) p_an(i,j,k)=0.
      end if

      if(p_ijb(i,j,k).eq.2) then
      eavr = (p_dy(j+1)*p_EE(i,j,k)+p_dy(j)*p_EE(i,j+1,k))
     .       /(p_dy(j)+p_dy(j+1))
      yplus = 0.5*dx(i)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i,j+1,k))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*dx(i))
      endif

      p_spv(i,j,k) = utau*p_dely(j)*dz(k)
     .            *abs(p_afba(i+1,j,k)-p_afba(i,j,k))
      p_apy(i,j,k) = p_apy(i,j,k) - p_spv(i,j,k)
      endif

  280 continue

c  at the horizontal boundaries
c  x = 0
c  shear-free or outflow conditions?


      do 320 k=2,kmax1
      do 320 j=p_is_u(rank),p_ie_u(rank)
      if((infw(1,j,k).eq.0).or.(infw(1,j,k).eq.2)) then
      if(p_ijb(2,j,k).ne.0) then
      p_apy(2,j,k) = p_apy(2,j,k)-p_aw(2,j,k)
      p_aw(2,j,k)  = 0.
      end if
      end if
  320 continue
c  inflow conditions?
      do 340 k=2,kmax1
      do 340 j=p_is_u(rank),p_ie_u(rank)
      if(infw(1,j,k).eq.1) then
      if(p_ijb(2,j,k).ne.0) then
      p_s(2,j,k)  = p_s(2,j,k)+p_vv(1,j,k)*p_aw(2,j,k)
      p_aw(2,j,k) = 0.              !iss!
      end if
      end if
  340 continue


c  x = xmax
c  shear-free or outflow conditions?

      do 360 k=2,kmax1
      do 360 j=p_is_u(rank),p_ie_u(rank)
      if((infe(imax2,j,k).eq.0).or.(infe(imax2,j,k).eq.2)) then
      if(p_ijb(imax1,j,k).ne.0) then
      p_apy(imax1,j,k) = p_apy(imax1,j,k)-p_ae(imax1,j,k)
      p_ae(imax1,j,k)  = 0.
      end if
      end if
  360 continue
c  inflow conditions?

      do 380 k=2,kmax1
      do 380 j=p_is_u(rank),p_ie_u(rank)
      if(infe(imax2,j,k).eq.1) then
      if(p_ijb(imax1,j,k).ne.0) then
      p_s(imax1,j,k)  = p_s(imax1,j,k)+p_vv(imax2,j,k)*p_ae(imax1,j,k)
      p_ae(imax1,j,k) = 0.                     !iee!
      end if
      end if
  380 continue



c  y = 0
c  shear-free or outflow conditions?
      if ( rank == 0 ) then ! WORKER 1 only for x = 0 ##################
      is   = p_is_u(rank) ! = 2
      iss  = p_is_g(rank) ! = 1

      do 400 k=2,kmax1
      do 400 i=2,imax1
      if((infs(i,iss,k).eq.0).or.(infs(i,iss,k).eq.2)) then
      if(p_ijb(i,is,k).ne.0) then
      p_apy(i,is,k) = p_apy(i,is,k)-p_as(i,is,k)
      p_as(i,is,k)  = 0.
      end if
      end if 
  400 continue
c  inflow conditions?
      do 420 k=2,kmax1
      do 420 i=2,imax1
      if(infs(i,iss,k).eq.1) then
      if(p_ijb(i,is,k).ne.0) then
      p_s(i,is,k)  = p_s(i,is,k)+p_vv(i,iss,k)*p_as(i,is,k)
      p_as(i,is,k) = 0.
      end if   
      end if
  420 continue
      end if

c  y = ymax
c  shear-free or outflow conditions?
      if ( rank == nworker-1 ) then ! WORKER nworker only for x = xmax ###
      ie   = p_ie_u(rank)  ! = imax1
      iee  = p_imax(rank) ! = imax2
      do 440 k=2,kmax1
      do 440 i=2,imax1
      if((infn(i,iee,k).eq.0).or.(infn(i,iee,k).eq.2)) then
      if(p_ijb(i,ie,k).ne.0) then
      p_apy(i,ie,k) = p_apy(i,ie,k)-p_an(i,ie,k)
      p_an(i,ie,k)  = 0.
      end if
      end if
  440 continue
c  inflow conditions?
      do 460 k=2,kmax1
      do 460 i=2,imax1
      if(infn(i,iee,k).eq.1) then
      if(p_ijb(i,ie,k).ne.0) then
      p_s(i,ie,k)  = p_s(i,ie,k)+p_vv(i,iee,k)*p_an(i,ie,k)
      p_an(i,ie,k) = 0.
      end if
      end if
  460 continue
      end if
      return


      end


cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_coefw
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  calculate the coefficients of the finite difference
c  equation for the z-momentum  equation
!----------------------------------------------------------------------!      
      use moment_dim
      use common_mpi
!----------------------------------------------------------------------!      
      
       p_al(:,:,:) = 0.
       p_ah(:,:,:) = 0.
       p_as(:,:,:) = 0.
       p_an(:,:,:) = 0.
       p_aw(:,:,:) = 0.
       p_ae(:,:,:) = 0.
      p_spw(:,:,:) = 0.

      do 200 k=2,kmax
      do 200 j=p_is_o(rank),p_ie_o(rank)
      do 200 i=2,imax1 ! 2~imax1
      if(p_ijc(i,j,k).eq.0) go to 200

      if(p_ijc(i-1,j,k).eq.0) then
      dlxm = 0.5*dx(i)
      else
      dlxm = delx(i-1)
      end if

      if(p_ijc(i+1,j,k).eq.0) then
      dlxp = 0.5*dx(i)
      else
      dlxp = delx(i)
      end if

      if(p_ijc(i,j-1,k).eq.0) then
      dlym = 0.5*p_dy(j)
      else
      dlym = p_dely(j-1)
      end if

      if(p_ijc(i,j+1,k).eq.0) then
      dlyp = 0.5*p_dy(j)
      else
      dlyp = p_dely(j)
      end if

      dl  =   p_vis(i,j,k)/dz(k)
      den = (p_dena(i,j,k)+p_dena(i,j,k)
     .      +p_dena(i,j,k)+p_dena(i,j,k))/4.
      fz  = den*(p_ww(i,j,k-1)+p_ww(i,j,k))/2.
      p_al(i,j,k) = dx(i)*p_dy(j)
     .            *(dl*amax1(0.,(1.-0.1*abs(fz)/dl)**5)+amax1(fz,0.))
     .            *p_afcc(i,j,k)

      dsvis = (p_dy(j-1)*(dz(k+1)*p_vis(i,j  ,k)+dz(k)*p_vis(i,j  ,k+1))
     .      + p_dy(j  )*(dz(k+1)*p_vis(i,j-1,k)+dz(k)*p_vis(i,j-1,k+1)))
     .     /((p_dy(j-1)+p_dy(j))*(dz(k)+dz(k+1)))

      ds  = dsvis/dlym
      den = (p_dena(i,j-1,k)+p_dena(i,j-1,k+1)
     .      +p_dena(i,j  ,k)+p_dena(i,j  ,k+1))/4.
      fy  = den*(dz(k+1)*p_vv(i,j-1,k)+dz(k)*p_vv(i,j-1,k+1))
     .     /(dz(k)+dz(k+1))
      p_as(i,j,k) = dx(i)*delz(k)
     .            *(ds*amax1(0.,(1.-0.1*abs(fy)/ds)**5)+amax1(fy,0.))
     .            *p_afcb(i,j-1,k)

      dwvis =(dx(i-1)*(dz(k+1)*p_vis(i  ,j,k)+dz(k)*p_vis(i  ,j,k+1))
     .       +dx(i  )*(dz(k+1)*p_vis(i-1,j,k)+dz(k)*p_vis(i-1,j,k+1)))
     .     /((dx(i-1)+dx(i))*(dz(k)+dz(k+1)))

      dw  = dwvis/dlxm
      den = (p_dena(i-1,j,k)+p_dena(i-1,j,k+1)
     .      +p_dena(i  ,j,k)+p_dena(i  ,j,k+1))/4.
      fx  = den*(dz(k+1)*p_uu(i-1,j,k)+dz(k)*p_uu(i-1,j,k+1))
     .     /(dz(k)+dz(k+1))
      p_aw(i,j,k) = p_dy(j)*delz(k)
     .            *(dw*amax1(0.,(1.-0.1*abs(fx)/dw)**5)+amax1(fx,0.))
     .            *p_afca(i,j,k)

      devis = (dx(i  )*(dz(k+1)*p_vis(i+1,j,k)+dz(k)*p_vis(i+1,j,k+1))
     .        +dx(i+1)*(dz(k+1)*p_vis(i  ,j,k)+dz(k)*p_vis(i,j,k+1)))
     .     /((dx(i)+dx(i+1))*(dz(k)+dz(k+1)))

      de  = devis/dlxp
      den = (p_dena(i  ,j,k)+p_dena(i  ,j,k+1)
     .      +p_dena(i+1,j,k)+p_dena(i+1,j,k+1))/4.
      fx  = den*(dz(k+1)*p_uu(i,j,k)+dz(k)*p_uu(i,j,k+1))
     .     /(dz(k)+dz(k+1))
      p_ae(i,j,k) = p_dy(j)*delz(k)
     .            *(de*amax1(0.,(1.-0.1*abs(fx)/de)**5)+amax1(0.,-fx))
     .            *p_afca(i+1,j,k)

      dnvis = (p_dy(j  )*(dz(k+1)*p_vis(i,j+1,k)+dz(k)*p_vis(i,j+1,k+1))
     .      + p_dy(j+1)*(dz(k+1)*p_vis(i,j  ,k)+dz(k)*p_vis(i,j  ,k+1)))
     .     /((p_dy(j)+p_dy(j+1))*(dz(k)+dz(k+1)))

      dn  = dnvis/dlyp
      den = (p_dena(i,j  ,k)+p_dena(i,j  ,k+1)
     .      +p_dena(i,j+1,k)+p_dena(i,j+1,k+1))/4.
      fy  = den*(dz(k+1)*p_vv(i,j,k)+dz(k)*p_vv(i,j,k+1))
     .     /(dz(k)+dz(k+1))
      p_an(i,j,k) = dx(i)*delz(k)
     .             *(dn*amax1(0.,(1.-0.1*abs(fy)/dn)**5)+amax1(0.,-fy))
     .             *p_afcb(i,j,k)

      dh  = p_vis(i,j,k+1)/dz(k+1)
      den = (p_dena(i,j,k+1)+p_dena(i,j,k+1)
     .      +p_dena(i,j,k+1)+p_dena(i,j,k+1))/4.
      fz  = den*(p_ww(i,j,k)+p_ww(i,j,k+1))/2.
      p_ah(i,j,k) = dx(i)*p_dy(j)
     .            *(dh*amax1(0.,(1.-0.1*abs(fz)/dh)**5)+amax1(0.,-fz))
     .            *p_afcc(i,j,k+1)

      p_apz(i,j,k) = (p_denao(i,j,k)+p_denao(i,j,k+1))
     .             *dx(i)*p_dy(j)*delz(k)*p_afcv(i,j,k)/(2.*delt)
     .             +p_ae(i,j,k)+p_aw(i,j,k)+p_an(i,j,k)
     .             +p_as(i,j,k)+p_ah(i,j,k)+p_al(i,j,k)

      sorw1 = -2./3.*(p_EE(i,j,k+1)-p_EE(i,j,k))/delz(k)

      sorw2 = ( p_vis(i,j,k+1)*(p_ww(i,j,k+1)-p_ww(i,j,k  ))/dz(k+1)
     .         -p_vis(i,j,k  )*(p_ww(i,j,k  )-p_ww(i,j,k-1))/dz(k  ))
     .      /delz(k)

      sorw3 = (devis*(p_uu(i  ,j,k+1)-p_uu(i  ,j,k))/delz(k)
     .        -dwvis*(p_uu(i-1,j,k+1)-p_uu(i-1,j,k))/delz(k))/dx(i)

      sorw4 = (dnvis*(p_vv(i,j  ,k+1)-p_vv(i,j  ,k))/delz(k)
     .        -dsvis*(p_vv(i,j-1,k+1)-p_vv(i,j-1,k))/delz(k))/p_dy(j)

      alpa = 0.5*(p_denao(i,j,k)+p_denao(i,j,k+1))

      if(ither.eq.1) then
      t1 = (dz(k)*p_tt(i,j,k+1)+dz(k+1)*p_tt(i,j,k))/(dz(k)+dz(k+1))
      t2 = (dz(k)*p_ref(i,j,k+1)+dz(k+1)*p_ref(i,j,k))/(dz(k)+dz(k+1))
      beta = alpa*(t1-t2)/t2*gravity*dx(i)*p_dy(j)*delz(k)
      else
      beta = 0.
      endif

      p_s(i,j,k) = alpa*dx(i)*p_dy(j)*delz(k)*p_afcv(i,j,k)
     .   *p_wwo(i,j,k)/delt-
     .   dx(i)*p_dy(j)*(p_po(i,j,k+1)-p_po(i,j,k))*p_afsc(i,j,k+1)
     .   + beta
     .   +(p_dena(i,j,k)+p_dena(i,j,k+1))/2.
     .   *(sorw1+sorw2+sorw3+sorw4)*dx(i)*p_dy(j)*delz(k)
     .   *p_afcv(i,j,k)

cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c Drag force by trees

      IF (itree .eq. 1) then ! HJ tree
      IF (p_itc(i,j,k) .eq. 0) then 
      tu1 =(dz(k+1)*p_uu(i-1,j,k)+dz(k)*p_uu(i-1,j,k+1))/(dz(k)+dz(k+1))
      tu2 =(dz(k+1)*p_uu(i,j,k)+dz(k)*p_uu(i,j,k+1))/(dz(k)+dz(k+1))

      tv1 =(dz(k+1)*p_vv(i,j-1,k)+dz(k)*p_vv(i,j-1,k+1))/(dz(k)+dz(k+1))
      tv2 =(dz(k+1)*p_vv(i,j,k)+dz(k)*p_vv(i,j,k+1))/(dz(k)+dz(k+1))

      vel =sqrt(p_wwo(i,j,k)**2.+0.25*(tu1+tu2)**2.+0.25*(tv1+tv2)**2.)
      p_spz(i,j,k) = -0.5*(p_dena(i,j,k)+p_dena(i,j,k+1))
     .             *p_cdrag(i,j,k)*p_tfrac(i,j,1)*p_dleaf(i,j,1)*vel
      p_apz(i,j,k) = p_apz(i,j,k) - p_spz(i,j,k)
      end if
      endif
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc

  200 continue

c  implement boundary conditions
c  at the lower boundary 
      do 220 j=p_is_o(rank),p_ie_o(rank)
      do 220 i=2,imax1 ! 2~imax1
      if(p_ijc(i,j,2).ne.0) p_al(i,j,2)=0.
  220 continue

c  at the upper boundary (shear-free flow)
      do 240 j=p_is_o(rank),p_ie_o(rank)
      do 240 i=2,imax1 ! 2~imax1
      p_apz(i,j,kmax) = p_apz(i,j,kmax)-p_ah(i,j,kmax)
      p_ah(i,j,kmax)  = 0.
  240 continue

c  at the top of the buildings 
      do 260 k=3,kmax
      do 260 j=p_is_o(rank),p_ie_o(rank)
      do 260 i=2,imax1 ! 2~imax1
      if((p_ijc(i,j,k).ne.0).and.(p_ijc(i,j,k-1).eq.0)) p_al(i,j,k)=0.
      if((p_ijc(i,j,k).ne.0).and.(p_ijc(i,j,k+1).eq.0)) p_ah(i,j,k)=0.
  260 continue

c  at the building walls 
      do 280 k=2,kmax
      do 280 j=p_is_o(rank),p_ie_o(rank)
      do 280 i=2,imax1 ! 2~imax1

      if(p_ijc(i,j,k).eq.1) then

      if(p_ijc(i-1,j,k).ne.1) then

      eavr = (dz(k+1)*p_EE(i,j,k)+dz(k)*p_EE(i,j,k+1))/(dz(k)+dz(k+1))
      yplus = 0.5*dx(i)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i,j,k+1))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*dx(i))
      endif

      p_spw(i,j,k) = utau*delz(k)*p_dy(j)*(1.-p_afca(i,j,k))
      p_apz(i,j,k) = p_apz(i,j,k) - p_spw(i,j,k)
      endif

      if(p_ijc(i+1,j,k).ne.1) then

      eavr = (dz(k+1)*p_EE(i,j,k)+dz(k)*p_EE(i,j,k+1))/(dz(k)+dz(k+1))
      yplus = 0.5*dx(i)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i,j,k+1))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*dx(i))
      endif

      p_spw(i,j,k) = utau*delz(k)*p_dy(j)*(1.-p_afca(i+1,j,k))
      p_apz(i,j,k) = p_apz(i,j,k) - p_spw(i,j,k)
      endif

      if(p_ijc(i,j-1,k).ne.1) then

      eavr = (dz(k+1)*p_EE(i,j,k)+dz(k)*p_EE(i,j,k+1))/(dz(k)+dz(k+1))
      yplus = 0.5*p_dy(j)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i,j,k+1))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*p_dy(j))
      endif

      p_spw(i,j,k) = utau*delz(k)*dx(i)*(1.-p_afcb(i,j-1,k))
      p_apz(i,j,k) = p_apz(i,j,k) - p_spw(i,j,k)
      endif

      if(p_ijc(i,j+1,k).ne.1) then

      eavr = (dz(k+1)*p_EE(i,j,k)+dz(k)*p_EE(i,j,k+1))/(dz(k)+dz(k+1))
      yplus = 0.5*p_dy(j)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i,j,k+1))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*p_dy(j))
      endif

      p_spw(i,j,k) = utau*delz(k)*dx(i)*(1.-p_afcb(i,j,k))
      p_apz(i,j,k) = p_apz(i,j,k) - p_spw(i,j,k)
      endif
      end if

      if(p_ijc(i,j,k).eq.2) then
      eavr = (dz(k+1)*p_EE(i,j,k)+dz(k)*p_EE(i,j,k+1))/(dz(k)+dz(k+1))
      yplus = 0.5*dx(i)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i,j,k+1))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*dx(i))
      endif

      p_spw(i,j,k) = utau*delz(k)*p_dy(j)
     .            *abs(p_afca(i+1,j,k)-p_afca(i,j,k))
      p_apz(i,j,k) = p_apz(i,j,k) - p_spw(i,j,k)

      eavr = (dz(k+1)*p_EE(i,j,k)+dz(k)*p_EE(i,j,k+1))/(dz(k)+dz(k+1))
      yplus = 0.5*p_dy(j)*cu**0.25*eavr**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = -0.5*(p_dena(i,j,k)+p_dena(i,j,k+1))*cu**0.25*eavr**0.5
      uplus = alog(9.793*yplus)/tkapa
      utau  = deno1/uplus
      else
      utau  = -vism/(0.5*p_dy(j))
      endif

      p_spw(i,j,k) = utau*delz(k)*dx(i)
     .            *abs(p_afcb(i,j,k)-p_afcb(i,j-1,k))
      p_apz(i,j,k) = p_apz(i,j,k) - p_spw(i,j,k)
      endif

  280 continue

c  at the horizontal boundaries
c  x = 0
c  shear-free or outflow conditions?


      do 320 k=2,kmax
      do 320 j=p_is_o(rank),p_ie_o(rank)
      if((infw(1,j,k).eq.0).or.(infw(1,j,k).eq.2)) then
      if(p_ijc(2,j,k).ne.0) then
      p_apz(2,j,k) = p_apz(2,j,k)-p_aw(2,j,k)
      p_aw(2,j,k)  = 0.
      end if
      end if
  320 continue
c  inflow conditions?
      do 340 k=2,kmax
      do 340 j=p_is_o(rank),p_ie_o(rank)
      if(infw(1,j,k).eq.1) then
      if(p_ijc(2,j,k).ne.0) then
      p_s(2,j,k)  = p_s(2,j,k)+p_ww(1,j,k)*p_aw(2,j,k)
      p_aw(2,j,k) = 0.              !iss!
      end if
      end if
  340 continue


c  x = xmax
c  shear-free or outflow conditions?

      do 360 k=2,kmax
      do 360 j=p_is_o(rank),p_ie_o(rank)
      if((infe(imax2,j,k).eq.0).or.(infe(imax2,j,k).eq.2)) then
      if(p_ijc(imax1,j,k).ne.0) then
      p_apz(imax1,j,k) = p_apz(imax1,j,k)-p_ae(imax1,j,k)
      p_ae(imax1,j,k)  = 0.
      end if
      end if
  360 continue
c  inflow conditions?
      do 380 k=2,kmax
      do 380 j=p_is_o(rank),p_ie_o(rank)
      if(infe(imax2,j,k).eq.1) then
      if(p_ijc(imax1,j,k).ne.0) then
       p_s(imax1,j,k) = p_s(imax1,j,k)+p_ww(imax2,j,k)*p_ae(imax1,j,k)
      p_ae(imax1,j,k) = 0.                  !iee!
      end if
      end if
  380 continue


c  y = 0
c  shear-free or outflow conditions?
      if ( rank == 0 ) then ! WORKER 1 only for x = 0 ##################
      is   = p_is_o(rank) ! = 2
      iss  = p_is_g(rank) ! = 1
      do 400 k=2,kmax
      do 400 i=2,imax1 ! 2~imax1
      if((infs(i,iss,k).eq.0).or.(infs(i,iss,k).eq.2)) then
      if(p_ijc(i,is,k).ne.0) then
      p_apz(i,is,k) = p_apz(i,is,k)-p_as(i,is,k)
       p_as(i,is,k) = 0.
      end if
      end if
  400 continue
c  inflow conditions?
      do 420 k=2,kmax
      do 420 i=2,imax1 ! 2~imax1
      if(infs(i,iss,k).eq.1) then
      if(p_ijc(i,is,k).ne.0) then
       p_s(i,is,k) = p_s(i,is,k)+p_ww(i,iss,k)*p_as(i,is,k)
      p_as(i,is,k) = 0.
      end if
      end if
  420 continue
      endif

c  y = ymax
c  shear-free or outflow conditions?
      if ( rank == nworker-1 ) then ! WORKER nworker only for x = xmax ###
      ie   = p_ie_o(rank)  ! = imax1
      iee  = p_imax1(rank) ! = imax2
      do 440 k=2,kmax
      do 440 i=2,imax1 ! 2~imax1
      if((infn(i,iee,k).eq.0).or.(infn(i,iee,k).eq.2)) then
      if(p_ijc(i,ie,k).ne.0) then
      p_apz(i,ie,k) = p_apz(i,ie,k)-p_an(i,ie,k)
      p_an(i,ie,k)  = 0.
      end if
      end if
  440 continue
c  inflow conditions?
      do 460 k=2,kmax
      do 460 i=2,imax1 ! 2~imax1
      if(infn(i,iee,k).eq.1) then
      if(p_ijc(i,ie,k).ne.0) then
      p_s(i,ie,k)  = p_s(i,ie,k)+p_ww(i,iee,k)*p_an(i,ie,k)
      p_an(i,ie,k) = 0.
      end if
      end if
  460 continue
      endif
      return

      end


cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_coefE
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  calculate the coefficients of the finite difference
c  equation for the temperature equation
!----------------------------------------------------------------------! 
      use moment_dim
      use common_mpi
!----------------------------------------------------------------------! 


      p_visee(:,:,:) = (p_vis(:,:,:))/sigE
         p_al(:,:,:) = 0.
         p_ah(:,:,:) = 0.
         p_as(:,:,:) = 0.
         p_an(:,:,:) = 0.
         p_aw(:,:,:) = 0.
         p_ae(:,:,:) = 0.
        p_spE(:,:,:) = 0.
        p_swE(:,:,:) = 0.

      do 200 k=2,kmax1
      do 200 j=p_is_o(rank),p_ie_o(rank)
      do 200 i=2,imax1 ! 2~imax1

      if(p_ijc(i,j,k).eq.0) go to 200

      if(p_ijc(i,j,k-1).eq.0) then
      dlzm = 0.5*dz(k)
      else
      dlzm = delz(k-1)
      end if

      if(p_ijc(i,j,k+1).eq.0) then
      dlzp = 0.5*dz(k)
      else
      dlzp = delz(k)
      end if

      if(p_ijc(i-1,j,k).eq.0) then
      dlxm = 0.5*dx(i)
      else
      dlxm = delx(i-1)
      end if

      if(p_ijc(i+1,j,k).eq.0) then
      dlxp = 0.5*dx(i)
      else
      dlxp = delx(i)
      end if

      if(p_ijc(i,j-1,k).eq.0) then
      dlym = 0.5*p_dy(j)
      else
      dlym = p_dely(j-1)
      end if

      if(p_ijc(i,j+1,k).eq.0) then
      dlyp = 0.5*p_dy(j)
      else
      dlyp = p_dely(j)
      end if

      dl  = (dz(k)*p_visee(i,j,k-1)+dz(k-1)*p_visee(i,j,k))
     .      /((dz(k-1)+dz(k))*dlzm)
      den = (p_dena(i,j,k-1)+p_dena(i,j,k-1)
     .      +p_dena(i,j,k  )+p_dena(i,j,k  ))/4.
      fz  = den*p_ww(i,j,k-1)
      p_al(i,j,k) = dx(i)*p_dy(j)
     .            *(dl*amax1(0.,(1.-0.1*abs(fz)/dl)**5)+amax1(fz,0.))
     .            *p_afsc(i,j,k)

      ds  = (p_dy(j)*p_visee(i,j-1,k)+p_dy(j-1)*p_visee(i,j,k))
     .      /((p_dy(j-1)+p_dy(j))*dlym)
      den = (p_dena(i,j-1,k)+p_dena(i,j-1,k)
     .      +p_dena(i,j  ,k)+p_dena(i,j  ,k))/4.
      fy  = den*p_vv(i,j-1,k)
      p_as(i,j,k) = dx(i)*dz(k)
     .            *(ds*amax1(0.,(1.-0.1*abs(fy)/ds)**5)+amax1(fy,0.))
     .            *p_afsb(i,j-1,k)

      dw  = (dx(i)*p_visee(i-1,j,k)+dx(i-1)*p_visee(i,j,k))
     .      /((dx(i-1)+dx(i))*dlxm)
      den = (p_dena(i-1,j,k)+p_dena(i-1,j,k)
     .      +p_dena(i  ,j,k)+p_dena(i  ,j,k))/4.
      fx  = den*p_uu(i-1,j,k)
      p_aw(i,j,k) = p_dy(j)*dz(k)
     .            *(dw*amax1(0.,(1.-0.1*abs(fx)/dw)**5)+amax1(fx,0.))
     .            *p_afsa(i,j,k)

      de  = (dx(i+1)*p_visee(i,j,k)+dx(i)*p_visee(i+1,j,k))
     .      /((dx(i)+dx(i+1))*dlxp)
      den = (p_dena(i  ,j,k)+p_dena(i  ,j,k)
     .      +p_dena(i+1,j,k)+p_dena(i+1,j,k))/4.
      fx  = den*p_uu(i,j,k)
      p_ae(i,j,k) = p_dy(j)*dz(k)
     .            *(de*amax1(0.,(1.-0.1*abs(fx)/de)**5)+amax1(0.,-fx))
     .            *p_afsa(i+1,j,k)

      dn  = (p_dy(j+1)*p_visee(i,j,k)+p_dy(j)*p_visee(i,j+1,k))
     .      /((p_dy(j)+p_dy(j+1))*dlyp)
      den = (p_dena(i,j  ,k)+p_dena(i,j  ,k)
     .      +p_dena(i,j+1,k)+p_dena(i,j+1,k))/4.
      fy  = den*p_vv(i,j,k)
      p_an(i,j,k) = dx(i)*dz(k)
     .            *(dn*amax1(0.,(1.-0.1*abs(fy)/dn)**5)+amax1(0.,-fy))
     .            *p_afsb(i,j,k)

      dh  = (dz(k+1)*p_visee(i,j,k)+dz(k)*p_visee(i,j,k+1))
     .      /((dz(k)+dz(k+1))*dlzp)
      den = (p_dena(i,j,k  )+p_dena(i,j,k  )
     .      +p_dena(i,j,k+1)+p_dena(i,j,k+1))/4.
      fz  = den*p_ww(i,j,k)
      p_ah(i,j,k) = dx(i)*p_dy(j)
     .            *(dh*amax1(0.,(1.-0.1*abs(fz)/dh)**5)+amax1(0.,-fz))
     .            *p_afsc(i,j,k+1)

      xv1  = (dx(i+1)*(p_vv(i  ,j-1,k)+p_vv(i  ,j,k))+
     .        dx(i  )*(p_vv(i+1,j-1,k)+p_vv(i+1,j,k)))
     .     /(2.*(dx(i)+dx(i+1)))
      xv2  = (dx(i  )*(p_vv(i-1,j-1,k)+p_vv(i-1,j,k))+
     .        dx(i-1)*(p_vv(i  ,j-1,k)+p_vv(i  ,j,k)))
     .     /(2.*(dx(i-1)+dx(i)))

      xw1  = (dx(i+1)*(p_ww(i  ,j,k-1)+p_ww(i  ,j,k))+
     .        dx(i  )*(p_ww(i+1,j,k-1)+p_ww(i+1,j,k)))
     .     /(2.*(dx(i)+dx(i+1)))
      xw2  = (dx(i  )*(p_ww(i-1,j,k-1)+p_ww(i-1,j,k))+
     .        dx(i-1)*(p_ww(i  ,j,k-1)+p_ww(i  ,j,k)))
     .     /(2.*(dx(i-1)+dx(i)))

      yu1  = (p_dy(j+1)*(p_uu(i-1,j  ,k)+p_uu(i,j  ,k))+
     .        p_dy(j  )*(p_uu(i-1,j+1,k)+p_uu(i,j+1,k)))
     .     /(2.*(p_dy(j)+p_dy(j+1)))
      yu2  = (p_dy(j  )*(p_uu(i-1,j-1,k)+p_uu(i,j-1,k))+
     .        p_dy(j-1)*(p_uu(i-1,j  ,k)+p_uu(i,j  ,k)))
     .     /(2.*(p_dy(j-1)+p_dy(j)))

      yw1  = (p_dy(j+1)*(p_ww(i,j  ,k-1)+p_ww(i,j  ,k))+
     .        p_dy(j  )*(p_ww(i,j+1,k-1)+p_ww(i,j+1,k)))
     .     /(2.*(p_dy(j)+p_dy(j+1)))
      yw2  = (p_dy(j  )*(p_ww(i,j-1,k-1)+p_ww(i,j-1,k))+
     .        p_dy(j-1)*(p_ww(i,j  ,k-1)+p_ww(i,j  ,k)))
     .     /(2.*(p_dy(j-1)+p_dy(j)))

      zu1  = (dz(k+1)*(p_uu(i-1,j,k  )+p_uu(i,j,k  ))+
     .        dz(k  )*(p_uu(i-1,j,k+1)+p_uu(i,j,k+1)))
     .     /(2.*(dz(k)+dz(k+1)))
      zu2  = (dz(k  )*(p_uu(i-1,j,k-1)+p_uu(i,j,k-1))+
     .        dz(k-1)*(p_uu(i-1,j,k  )+p_uu(i,j,k  ))) 
     .     /(2.*(dz(k-1)+dz(k)))

      zv1  = (dz(k+1)*(p_vv(i,j-1,k  )+p_vv(i,j,k  ))+
     .        dz(k  )*(p_vv(i,j-1,k+1)+p_vv(i,j,k+1)))
     .     /(2.*(dz(k)+dz(k+1)))
      zv2  = (dz(k  )*(p_vv(i,j-1,k-1)+p_vv(i,j,k-1))+
     .        dz(k-1)*(p_vv(i,j-1,k  )+p_vv(i,j,k  )))
     .     /(2.*(dz(k-1)+dz(k)))

      dudx = (p_uu(i,j,k)-p_uu(i-1,j,k))/dx(i)
      dvdx = (xv1-xv2)/dx(i)
      dwdx = (xw1-xw2)/dx(i)
      dudy = (yu1-yu2)/p_dy(j)
      dvdy = (p_vv(i,j,k)-p_vv(i,j-1,k))/p_dy(j)
      dwdy = (yw1-yw2)/p_dy(j)
      dudz = (zu1-zu2)/dz(k)
      dvdz = (zv1-zv2)/dz(k)
      dwdz = (p_ww(i,j,k)-p_ww(i,j,k-1))/dz(k)

      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

      !--- For i = imax1
!     .   (rank.eq.nworker-1 .and. i.eq.p_ie_o(rank)) ) then
      if((p_ijc(i+1,j,k).eq.0) .or.(i.eq.imax1)) then
      dvdx = (p_vv(i,j,k)+p_vv(i,j-1,k  )-2.*xv2)/(2.*dx(i))
      dwdx = (p_ww(i,j,k)+p_ww(i,j  ,k-1)-2.*xw2)/(2.*dx(i))
      endif

      !--- For i = 1
!     .   (rank.eq.0         .and. i.eq.p_is_o(rank)) ) then
      if((p_ijc(i-1,j,k).eq.0) .or.(i.eq.2)) then
      dvdx = (2.*xv1-p_vv(i,j,k)-p_vv(i,j-1,k  ))/(2.*dx(i))
      dwdx = (2.*xw1-p_ww(i,j,k)-p_ww(i,j  ,k-1))/(2.*dx(i))
      endif

      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

      if((p_ijc(i,j+1,k).eq.0).or.
     .   (rank.eq.nworker-1 .and. j.eq.p_ie_o(rank)) ) then
      dudy = (p_uu(i,j,k)+p_uu(i-1,j,k  )-2.*yu2)/(2.*p_dy(j))
      dwdy = (p_ww(i,j,k)+p_ww(i  ,j,k-1)-2.*yw2)/(2.*p_dy(j))
      endif

      if((p_ijc(i,j-1,k).eq.0).or.
     .   (rank.eq.0         .and. j.eq.p_is_o(rank)) ) then
      dudy = (2.*yu1-p_uu(i,j,k)-p_uu(i-1,j,k  ))/(2.*p_dy(j))
      dwdy = (2.*yw1-p_ww(i,j,k)-p_ww(i  ,j,k-1))/(2.*p_dy(j))
      endif

      if((p_ijc(i,j,k+1).eq.0).or.(k.eq.kmax1)) then
      dudz = (p_uu(i,j,k)+p_uu(i-1,j  ,k)-2.*zu2)/(2.*dz(k))
      dvdz = (p_vv(i,j,k)+p_vv(i  ,j-1,k)-2.*zv2)/(2.*dz(k))
      endif

      if(p_ijc(i,j,k-1).eq.0) then
      dudz = (2.*zu1-p_uu(i,j,k)-p_uu(i-1,j  ,k))/(2.*dz(k))
      dvdz = (2.*zv1-p_vv(i,j,k)-p_vv(i  ,j-1,k))/(2.*dz(k))
      endif

      p_diff(i,j,k) = (dudy+dvdx)**2+(dudz+dwdx)**2+(dvdz+dwdy)**2
     .              + 2.*(dudx**2+dvdy**2+dwdz**2)

      if(ither.eq.1) then

      if(p_ijc(i,j,k-1).eq.1) then
      t1 = (dz(k  )*p_tt(i,j,k+1)+dz(k+1)*p_tt(i,j,k  ))/(dz(k)+dz(k+1))
      t2 = (dz(k-1)*p_tt(i,j,k  )+dz(k  )*p_tt(i,j,k-1))/(dz(k-1)+dz(k))
      dtdz = (t1-t2)/dz(k)
      else
      t1 = (dz(k  )*p_tt(i,j,k+1)+dz(k+1)*p_tt(i,j,k  ))/(dz(k)+dz(k+1))
      dtdz = (t1 - p_tt(i,j,k))/(0.5*dz(k))
      endif 

      else
      dtdz = 0.
      endif

      p_scE1(i,j,k) =  p_dena(i,j,k)*p_vis(i,j,k)*p_diff(i,j,k)
      p_scE2(i,j,k) = -p_dena(i,j,k)*p_DD(i,j,k)

      p_apEE(i,j,k) = p_denao(i,j,k)*dx(i)*p_dy(j)*dz(k)
     .             *p_afsv(i,j,k)/delt+
     .                   p_ae(i,j,k)+p_aw(i,j,k)+p_an(i,j,k) +
     .                   p_as(i,j,k)+p_ah(i,j,k)+p_al(i,j,k)

      p_s(i,j,k) = p_denao(i,j,k)*dx(i)*p_dy(j)*dz(k)
     .           *p_afsv(i,j,k)*p_EEo(i,j,k)/delt
     .           + (p_scE1(i,j,k)+p_scE2(i,j,k))
     .           *dx(i)*p_dy(j)*dz(k)*p_afsv(i,j,k)
     .           -p_dena(i,j,k)*gravity*p_vis(i,j,k)*dtdz
     .           /(p_ref(i,j,k)*Prt)*dx(i)*p_dy(j)*dz(k)*p_afsv(i,j,k)
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c Drag force by trees

      IF (itree .eq. 1) then ! HJ tree
      IF (p_itc(i,j,k) .eq. 0) then
      tu = (p_uu(i-1,j,k)+p_uu(i,j,k))/2.
      tv = (p_vv(i,j-1,k)+p_vv(i,j,k))/2.
      tw = (p_ww(i,j,k-1)+p_ww(i,j,k))/2.

      vel  = sqrt(tu**2.+tv**2.+tw**2.)
      p_spEp(i,j,k) = -4.0*p_dena(i,j,k)
     .              *p_cdrag(i,j,k)*p_tfrac(i,j,1)*p_dleaf(i,j,1)*vel
      p_spEu(i,j,k)=p_dena(i,j,k)*p_cdrag(i,j,k)*p_tfrac(i,j,1)
     .   *p_dleaf(i,j,1)

      p_s(i,j,k) = p_s(i,j,k) + p_spEu(i,j,k)
      p_apEE(i,j,k) = p_apEE(i,j,k) - p_spEp(i,j,k)
      end if
      endif
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc

  200 continue

c  implement boundary conditions
c  at the lower boundary 
      do 220 j=p_is_o(rank),p_ie_o(rank)
      do 220 i=2,imax1

      if(p_ijc(i,j,2).ne.0) then
!      yplus = 0.5*dz(2)*cu**0.25*p_EE(i,j,2)**0.5/visl
      yplus = 0.5*dz(2)*cu**0.25*p_EEo(i,j,2)**0.5/visl
      velu = abs((p_uu(i,j,2)+p_uu(i-1,j  ,2))/2.)
      velv = abs((p_vv(i,j,2)+p_vv(i  ,j-1,2))/2.)
      vsqr = velu**2+velv**2
      uplus = alog(9.793*yplus)/tkapa
!      deno1 = -p_dena(i,j,2)*cu**0.75*p_EE(i,j,2)**0.5
      deno1 = -p_dena(i,j,2)*cu**0.75*p_EEo(i,j,2)**0.5
      p_spE(i,j,2) = 2.*deno1*uplus*dx(i)*p_dy(j)
c     p_spE(i,j,2) = -1.E30
      p_apEE(i,j,2) = p_apEE(i,j,2) - p_spE(i,j,2)
      p_al(i,j,2)=0.
      
      if(yplus.gt.ynd) then
!      utau = p_dena(i,j,2)*cu**0.25*p_EE(i,j,2)**0.5*vsqr/uplus
      utau = p_dena(i,j,2)*cu**0.25*p_EEo(i,j,2)**0.5*vsqr/uplus
      else
      utau = vism*vsqr/(0.5*dz(2))
      endif

      p_swE(i,j,2) = 2.*utau*dx(i)*p_dy(j)
      p_s(i,j,2) = p_s(i,j,2) + p_swE(i,j,2)

      endif

  220 continue

c  at the top of the model (shear-free condition)
      do 240 j=p_is_o(rank),p_ie_o(rank)
      do 240 i=2,imax1 ! 2~imax1
      p_apEE(i,j,kmax1) = p_apEE(i,j,kmax1)-p_ah(i,j,kmax1)
        p_ah(i,j,kmax1) = 0.
  240 continue

c  at the top of the buildings 
      do 260 k=3,kmax1
      do 260 j=p_is_o(rank),p_ie_o(rank)
      do 260 i=2,imax1 ! 2~imax1

      if((p_ijc(i,j,k).eq.1).and.(p_ijc(i,j,k-1).ne.1)) then
!      yplus = 0.5*dz(k)*cu**0.25*p_EE(i,j,k)**0.5/visl
      yplus = 0.5*dz(k)*cu**0.25*p_EEo(i,j,k)**0.5/visl
      velu = abs((p_uu(i,j,k)+p_uu(i-1,j  ,k))/2.)
      velv = abs((p_vv(i,j,k)+p_vv(i  ,j-1,k))/2.)
      vsqr = velu**2+velv**2
      uplus = alog(9.793*yplus)/tkapa
!      deno1 = -p_dena(i,j,k)*cu**0.75*p_EE(i,j,k)**0.5
      deno1 = -p_dena(i,j,k)*cu**0.75*p_EEo(i,j,k)**0.5
      p_spE(i,j,k) = 2.*deno1*uplus*dx(i)*p_dy(j)*(1.-p_afsc(i,j,k))
c     p_spE(i,j,k) = -1.E30
      p_apEE(i,j,k) = p_apEE(i,j,k) - p_spE(i,j,k)
  
      if(yplus.gt.ynd) then
!      utau = p_dena(i,j,k)*cu**0.25*p_EE(i,j,k)**0.5*vsqr/uplus
      utau = p_dena(i,j,k)*cu**0.25*p_EEo(i,j,k)**0.5*vsqr/uplus
      else
      utau = vism*vsqr/(0.5*dz(k))
      endif

      p_swE(i,j,k) = 2.*utau*dx(i)*p_dy(j)*(1.-p_afsc(i,j,k))/uplus
c     p_swE(i,j,k) = vsqr/cu**0.5/uplus**2.*1.E30
      p_s(i,j,k) = p_s(i,j,k) + p_swE(i,j,k)
c     s(i,j,k) =  p_denao(i,j,k)*dx(i)*dy(j)*dz(k)*p_EEo(i,j,k)/delt
c    .           + p_swE(i,j,k)

      endif

      if((p_ijc(i,j,k).eq.1).and.(p_ijc(i,j,k+1).ne.1)) then

!      yplus = 0.5*dz(k)*cu**0.25*p_EE(i,j,k)**0.5/visl
      yplus = 0.5*dz(k)*cu**0.25*p_EEo(i,j,k)**0.5/visl
      velu = abs((p_uu(i,j,k)+p_uu(i-1,j  ,k))/2.)
      velv = abs((p_vv(i,j,k)+p_vv(i  ,j-1,k))/2.)
      vsqr = velu**2+velv**2
      uplus = alog(9.793*yplus)/tkapa
!      deno1 = -p_dena(i,j,k)*cu**0.75*p_EE(i,j,k)**0.5
      deno1 = -p_dena(i,j,k)*cu**0.75*p_EEo(i,j,k)**0.5
      p_spE(i,j,k) = 2.*deno1*uplus*dx(i)*p_dy(j)*(1.-p_afsc(i,j,k+1))
c     p_spE(i,j,k) = -1.E30
      p_apEE(i,j,k) = p_apEE(i,j,k) - p_spE(i,j,k)
  
      if(yplus.gt.ynd) then
!      utau = p_dena(i,j,k)*cu**0.25*p_EE(i,j,k)**0.5*vsqr/uplus
      utau = p_dena(i,j,k)*cu**0.25*p_EEo(i,j,k)**0.5*vsqr/uplus
      else
      utau = vism*vsqr/(0.5*dz(k))
      endif

      p_swE(i,j,k) = 2.*utau*dx(i)*p_dy(j)*(1.-p_afsc(i,j,k+1))/uplus
c     p_swE(i,j,k) = vsqr/cu**0.5/uplus**2.*1.E30
        p_s(i,j,k) = p_s(i,j,k) + p_swE(i,j,k)
c     s(i,j,k) =  p_denao(i,j,k)*dx(i)*dy(j)*dz(k)*p_EEo(i,j,k)/delt
c    .           + p_swE(i,j,k)

      endif

      if((p_ijc(i,j,k).eq.2)) then
      yplus = 0.5*dz(k)*cu**0.25*p_EEo(i,j,k)**0.5/visl
      velu = abs((p_uu(i,j,k)+p_uu(i-1,j,k))/2.)
      velv = abs((p_vv(i,j,k)+p_vv(i,j-1,k))/2.)
      vsqr = velu**2+velv**2
      uplus = alog(9.793*yplus)/tkapa
      deno1 = -p_dena(i,j,k)*cu**0.75*p_EEo(i,j,k)**0.5
      p_spE(i,j,k) = 2.*deno1*uplus*dx(i)*p_dy(j)
     .           *abs(p_afsc(i,j,k)-p_afsc(i,j,k+1))
      p_apEE(i,j,k) = p_apEE(i,j,k) - p_spE(i,j,k)

      if(yplus.gt.ynd) then
      utau = p_dena(i,j,k)*cu**0.25*p_EEo(i,j,k)**0.5*vsqr/uplus
      else
      utau = vism*vsqr/(0.5*dz(k))
      endif

      p_swE(i,j,k) = 2.*utau*dx(i)*p_dy(j)
     .           *abs(p_afsc(i,j,k)-p_afsc(i,j,k+1))/uplus
      p_s(i,j,k) = p_s(i,j,k) + p_swE(i,j,k)

      endif

  260 continue

c  at the building walls 
      do 280 k=2,kmax1
      do 280 j=p_is_o(rank),p_ie_o(rank)
      do 280 i=2,imax1

      if (p_ijc(i,j,k).eq.1) then

      if(p_ijc(i-1,j,k).ne.1) then 

!     yplus = 0.5*dx(i)*cu**0.25*p_EE(i,j,k)**0.5/visl
      yplus = 0.5*dx(i)*cu**0.25*p_EEo(i,j,k)**0.5/visl
      velv = abs((p_vv(i,j,k)+p_vv(i,j-1,k  ))/2.)
      velw = abs((p_ww(i,j,k)+p_ww(i,j  ,k-1))/2.)
      vsqr = velv**2+velw**2
      uplus = alog(9.793*yplus)/tkapa
!      deno1 = -p_dena(i,j,k)*cu**0.75*p_EE(i,j,k)**0.5
      deno1 = -p_dena(i,j,k)*cu**0.75*p_EEo(i,j,k)**0.5
      p_spE(i,j,k) = 2.*deno1*uplus*p_dy(j)*dz(k)*(1.-p_afsa(i,j,k))
c     p_spE(i,j,k) = -1.E30
      p_apEE(i,j,k) = p_apEE(i,j,k) - p_spE(i,j,k)
  
      if(yplus.gt.ynd) then
!      utau = p_dena(i,j,k)*cu**0.25*p_EE(i,j,k)**0.5*vsqr/uplus
      utau = p_dena(i,j,k)*cu**0.25*p_EEo(i,j,k)**0.5*vsqr/uplus
      else
      utau = vism*vsqr/(0.5*dx(i))
      endif

      p_swE(i,j,k) = 2.*utau*p_dy(j)*dz(k)*(1.-p_afsa(i,j,k))/uplus
c     p_swE(i,j,k) = vsqr/cu**0.5/uplus**2.*1.E30
      p_s(i,j,k) = p_s(i,j,k) + p_swE(i,j,k)
c     s(i,j,k) =  p_denao(i,j,k)*dx(i)*dy(j)*dz(k)*p_EEo(i,j,k)/delt
c    .           + p_swE(i,j,k)

      endif

      if(p_ijc(i+1,j,k).ne.1) then

!      yplus = 0.5*dx(i)*cu**0.25*p_EE(i,j,k)**0.5/visl
      yplus = 0.5*dx(i)*cu**0.25*p_EEo(i,j,k)**0.5/visl
      velv = abs((p_vv(i,j,k)+p_vv(i,j-1,k  ))/2.)
      velw = abs((p_ww(i,j,k)+p_ww(i,j  ,k-1))/2.)
      vsqr = velv**2+velw**2
      uplus = alog(9.793*yplus)/tkapa
!      deno1 = -p_dena(i,j,k)*cu**0.75*p_EE(i,j,k)**0.5
      deno1 = -p_dena(i,j,k)*cu**0.75*p_EEo(i,j,k)**0.5
      p_spE(i,j,k) = 2.*deno1*uplus*p_dy(j)*dz(k)*(1.-p_afsa(i+1,j,k))
c     p_spE(i,j,k) = -1.E30
      p_apEE(i,j,k) = p_apEE(i,j,k) - p_spE(i,j,k)
  
      if(yplus.gt.ynd) then
!      utau = p_dena(i,j,k)*cu**0.25*p_EE(i,j,k)**0.5*vsqr/uplus
      utau = p_dena(i,j,k)*cu**0.25*p_EEo(i,j,k)**0.5*vsqr/uplus
      else
      utau = vism*vsqr/(0.5*dx(i))
      endif

      p_swE(i,j,k) = 2.*utau*p_dy(j)*dz(k)*(1.-p_afsa(i+1,j,k))/uplus
c     p_swE(i,j,k) = vsqr/cu**0.5/uplus**2.*1.E30
      p_s(i,j,k)   = p_s(i,j,k) + p_swE(i,j,k)
c     s(i,j,k) =  p_denao(i,j,k)*dx(i)*dy(j)*dz(k)*p_EEo(i,j,k)/delt
c    .           + p_swE(i,j,k)

      endif

      if(p_ijc(i,j-1,k).ne.1) then

!      yplus = 0.5*p_dy(j)*cu**0.25*p_EE(i,j,k)**0.5/visl
      yplus = 0.5*p_dy(j)*cu**0.25*p_EEo(i,j,k)**0.5/visl
      velu = abs((p_uu(i,j,k)+p_uu(i-1,j,k  ))/2.)
      velw = abs((p_ww(i,j,k)+p_ww(i  ,j,k-1))/2.)
      vsqr = velu**2+velw**2
      uplus = alog(9.793*yplus)/tkapa
!      deno1 = -p_dena(i,j,k)*cu**0.75*p_EE(i,j,k)**0.5
      deno1 = -p_dena(i,j,k)*cu**0.75*p_EEo(i,j,k)**0.5
      p_spE(i,j,k) = 2.*deno1*uplus*dx(i)*dz(k)*(1.-p_afsb(i,j-1,k))
c     p_spE(i,j,k) = -1.E30
      p_apEE(i,j,k) = p_apEE(i,j,k) - p_spE(i,j,k)
  
      if(yplus.gt.ynd) then
!      utau = p_dena(i,j,k)*cu**0.25*p_EE(i,j,k)**0.5*vsqr/uplus
      utau = p_dena(i,j,k)*cu**0.25*p_EEo(i,j,k)**0.5*vsqr/uplus
      else
      utau = vism*vsqr/(0.5*p_dy(j))
      endif

      p_swE(i,j,k) = 2.*utau*dx(i)*dz(k)*(1.-p_afsb(i,j-1,k))/uplus
c     p_swE(i,j,k) = vsqr/cu**0.5/uplus**2.*1.E30
      p_s(i,j,k) = p_s(i,j,k) + p_swE(i,j,k)
c     s(i,j,k) =  p_denao(i,j,k)*dx(i)*dy(j)*dz(k)*p_EEo(i,j,k)/delt
c    .           + p_swE(i,j,k)

      endif

      if(p_ijc(i,j+1,k).ne.1) then

!      yplus = 0.5*p_dy(j)*cu**0.25*p_EE(i,j,k)**0.5/visl
      yplus = 0.5*p_dy(j)*cu**0.25*p_EEo(i,j,k)**0.5/visl
      velu = abs((p_uu(i,j,k)+p_uu(i-1,j,k  ))/2.)
      velw = abs((p_ww(i,j,k)+p_ww(i  ,j,k-1))/2.)
      vsqr = velu**2+velw**2
      uplus = alog(9.793*yplus)/tkapa
!      deno1 = -p_dena(i,j,k)*cu**0.75*p_EE(i,j,k)**0.5
      deno1 = -p_dena(i,j,k)*cu**0.75*p_EEo(i,j,k)**0.5
      p_spE(i,j,k) = 2.*deno1*uplus*dx(i)*dz(k)*(1.-p_afsb(i,j,k))
c     p_spE(i,j,k) = -1.E30
      p_apEE(i,j,k) = p_apEE(i,j,k) - p_spE(i,j,k)
  
      if(yplus.gt.ynd) then
!      utau = p_dena(i,j,k)*cu**0.25*p_EE(i,j,k)**0.5*vsqr/uplus
      utau = p_dena(i,j,k)*cu**0.25*p_EEo(i,j,k)**0.5*vsqr/uplus
      else
      utau = vism*vsqr/(0.5*p_dy(j))
      endif

      p_swE(i,j,k) = 2.*utau*dx(i)*dz(k)*(1.-p_afsb(i,j,k))/uplus
c     p_swE(i,j,k) = vsqr/cu**0.5/uplus**2.*1.E30
      p_s(i,j,k)   = p_s(i,j,k) + p_swE(i,j,k)
c     s(i,j,k) =  p_denao(i,j,k)*dx(i)*dy(j)*dz(k)*p_EEo(i,j,k)/delt
c    .           + p_swE(i,j,k)

      endif

      end if

      if (p_ijc(i,j,k).eq.2) then
      yplus = 0.5*dx(i)*cu**0.25*p_EEo(i,j,k)**0.5/visl
      velv = abs((p_vv(i,j,k)+p_vv(i,j-1,k))/2.)
      velw = abs((p_ww(i,j,k)+p_ww(i,j,k-1))/2.)
      vsqr = velv**2+velw**2
      uplus = alog(9.793*yplus)/tkapa
      deno1 = -p_dena(i,j,k)*cu**0.75*p_EEo(i,j,k)**0.5
      p_spE(i,j,k) = 2.*deno1*uplus*p_dy(j)*dz(k)
     .           *abs(p_afsa(i+1,j,k)-p_afsa(i,j,k))
      p_apEE(i,j,k) = p_apEE(i,j,k) - p_spE(i,j,k)
      if(yplus.gt.ynd) then
      utau = p_dena(i,j,k)*cu**0.25*p_EEo(i,j,k)**0.5*vsqr/uplus
      else
      utau = vism*vsqr/(0.5*dx(i))
      endif
      p_swE(i,j,k) = 2.*utau*p_dy(j)*dz(k)
     .           *abs(p_afsa(i+1,j,k)-p_afsa(i,j,k))/uplus
      p_s(i,j,k) = p_s(i,j,k) + p_swE(i,j,k)

      yplus = 0.5*p_dy(j)*cu**0.25*p_EEo(i,j,k)**0.5/visl
      velu = abs((p_uu(i,j,k)+p_uu(i-1,j,k))/2.)
      velw = abs((p_ww(i,j,k)+p_ww(i,j,k-1))/2.)
      vsqr = velu**2+velw**2
      uplus = alog(9.793*yplus)/tkapa
      deno1 = -p_dena(i,j,k)*cu**0.75*p_EEo(i,j,k)**0.5
      p_spE(i,j,k) = 2.*deno1*uplus*dx(i)*dz(k)
     .           *abs(p_afsb(i,j,k)-p_afsb(i,j-1,k))
      p_apEE(i,j,k) = p_apEE(i,j,k) - p_spE(i,j,k)
      if(yplus.gt.ynd) then
      utau = p_dena(i,j,k)*cu**0.25*p_EEo(i,j,k)**0.5*vsqr/uplus
      else
      utau = vism*vsqr/(0.5*p_dy(j))
      endif
      p_swE(i,j,k) = 2.*utau*dx(i)*dz(k)
     .           *abs(p_afsb(i,j,k)-p_afsb(i,j-1,k))/uplus
      p_s(i,j,k) = p_s(i,j,k) + p_swE(i,j,k)

      end if

  280 continue

c  at the horizontal boundaries


c  x = 0
c  shear-free or outflow conditions?


      do 320 k=2,kmax1
      do 320 j=p_is_o(rank),p_ie_o(rank)
      if((infw(1,j,k).eq.0).or.(infw(1,j,k).eq.2)) then
      if(p_ijc(2,j,k).ne.0) then
      p_apEE(2,j,k) = p_apEE(2,j,k)-p_aw(2,j,k)
      p_aw(2,j,k)   = 0.
      end if
      end if
  320 continue
c  inflow conditions?
      do 340 k=2,kmax1
      do 340 j=p_is_o(rank),p_ie_o(rank)
      if(infw(1,j,k).eq.1) then
      if(p_ijc(2,j,k).ne.0) then
      p_s(2,j,k)  = p_s(2,j,k)+p_EE(1,j,k)*p_aw(2,j,k)
      p_aw(2,j,k) = 0.              !iss!
      end if
      end if
  340 continue



c  x = xmax
c  shear-free or outflow conditions?


!c      iee  = p_ie_g(rank) ! = imax2

      do 360 k=2,kmax1
      do 360 j=p_is_o(rank),p_ie_o(rank)
      if((infe(imax2,j,k).eq.0).or.(infe(imax2,j,k).eq.2)) then
      if(p_ijc(imax1,j,k).ne.0) then
      p_apEE(imax1,j,k) = p_apEE(imax1,j,k)-p_ae(imax1,j,k)
      p_ae(imax1,j,k)   = 0.
      end if
      end if
  360 continue
c  inflow conditions?
      do 380 k=2,kmax1
      do 380 j=p_is_o(rank),p_ie_o(rank)
      if(infe(imax2,j,k).eq.1) then
      if(p_ijc(imax1,j,k).ne.0) then
       p_s(imax1,j,k) = p_s(imax1,j,k)+p_EE(imax2,j,k)*p_ae(imax1,j,k)
      p_ae(imax1,j,k) = 0.              !iee!
      end if
      end if
  380 continue


c  y = 0
c  shear-free or outflow conditions?

      if ( rank == 0 ) then ! WORKER 1 only for x = 0 ##################
      is   = p_is_o(rank) ! = 2
      iss  = p_is_g(rank) ! = 1
      do 400 k=2,kmax1
      do 400 i=2,imax1 ! 2~imax1
      if((infs(i,iss,k).eq.0).or.(infs(i,iss,k).eq.2)) then
      if(p_ijc(i,is,k).ne.0) then
      p_apEE(i,is,k) = p_apEE(i,is,k)-p_as(i,is,k)
        p_as(i,is,k) = 0.
      end if
      end if
  400 continue
c  inflow conditions?
      do 420 k=2,kmax1
      do 420 i=2,imax1 ! 2~imax1
      if(infs(i,iss,k).eq.1) then
      if(p_ijc(i,is,k).ne.0) then
       p_s(i,is,k) = p_s(i,is,k)+p_EE(i,iss,k)*p_as(i,is,k)
      p_as(i,is,k) = 0.
      end if
      end if
  420 continue
      end if

c  y = ymax
      if ( rank == nworker-1 ) then ! WORKER nworker only for x = xmax ###
      ie   = p_ie_o(rank)  ! = imax1
      iee  = p_imax1(rank) ! = imax2
      do 440 k=2,kmax1
      do 440 i=2,imax1 ! 2~imax1
      if((infn(i,iee,k).eq.0).or.(infn(i,iee,k).eq.2)) then
      if(p_ijc(i,ie,k).ne.0) then
      p_apEE(i,ie,k) = p_apEE(i,ie,k)-p_an(i,ie,k)
        p_an(i,ie,k) = 0.
      end if
      end if
  440 continue
c  inflow conditions?
      do 460 k=2,kmax1
      do 460 i=2,imax1 ! 2~imax1
      if(infn(i,iee,k).eq.1) then
      if(p_ijc(i,ie,k).ne.0) then
       p_s(i,ie,k) = p_s(i,ie,k)+p_EE(i,iee,k)*p_an(i,ie,k)
      p_an(i,ie,k) = 0.
      end if
      end if
  460 continue
      end if

      return

      end




cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_sorEE
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  successive overrelaxation with the relaxation parameter omega.
!----------------------------------------------------------------------!      
      use moment_dim
      use common_mpi
      !----------------------------------------------------------------!      
!     real(kind=8) :: etime,stime
      real :: resid,anorm,anorm_sum
      integer :: i,j,k,im,jm,n,ibdy
!----------------------------------------------------------------------!      
      
      do 220 n=1,maxits

      p_dum(:,:,:) = 0.0

!     stime=MPI_WTIME()
      call UPDATE_BUFFER_REAL(p_EE)
!     etime=MPI_WTIME()

      anorm = 0. ; anorm_sum = 0.
      if(mod(n,2).eq.0) then
      do 120 k=2,kmax1
      do 120 j=p_is_o(rank),p_ie_o(rank)
      do 120 i=2,imax1 ! 2~imax1
  120 p_dum(i,j,k) = p_EE(i,j,k)
      end if

!     call CPU_TIME(stime)

      do 140 k=2,kmax1
      do 140 j=p_is_o(rank),p_ie_o(rank)
      do 140 i=2,imax1 ! 2~imax1
      if(p_ijc(i,j,k).eq.0) go to 140
      if(p_odevn(i,j,k).eq.mod(n,2)) then
      resid =- p_s(i,j,k)
     .       -p_al(i,j,k)*p_EE(i  ,j  ,k-1)
     .       -p_as(i,j,k)*p_EE(i  ,j-1,k  )
     .       -p_aw(i,j,k)*p_EE(i-1,j  ,k  )
     .       -p_ah(i,j,k)*p_EE(i  ,j  ,k+1)
     .       -p_an(i,j,k)*p_EE(i  ,j+1,k  )
     .       -p_ae(i,j,k)*p_EE(i+1,j  ,k  )
     .     +p_apEE(i,j,k)*p_EE(i  ,j  ,k  )
      p_EE(i,j,k) = p_EE(i,j,k)-omegag*resid/p_apEE(i,j,k)
      if(p_EE(i,j,k).lt.1.E-10) p_EE(i,j,k) = 1.E-10
      end if
  140 continue
!     call CPU_TIME(etime)

c  convergence test
      if(mod(n,2).eq.0) then
      do 160 k=2,kmax1
      do 160 j=p_is_o(rank),p_ie_o(rank)
      do 160 i=2,imax ! 2~imax !! imax !!!!
                                         !          p_ie_u
      if(p_ijc(i,j,k).eq.0) go to 160
      if(abs(p_EE(i,j,k)).lt.cutE) go to 160
      anorm = anorm+abs((p_EE(i,j,k)-p_dum(i,j,k))/p_EE(i,j,k))
  160 continue
      anorm = anorm/float(itotal)

!     stime=MPI_WTIME()
      call MPI_ALLREDUCE(anorm,anorm_sum,1,MPI_REAL,
     .                   MPI_SUM,MPI_COMM_WORLD,ierr)
!     etime=MPI_WTIME()

      end if

      if (n.gt.1.and.(anorm_sum.lt.Ebmin)) then

! Will be parallelized -----------------------
!!     CALL UPDATE_BUFFER_REAL(EE) ! paral ! buffer update
!
!
!                    ! EE(2,j,k) in serial code
!        call MPI_SEND(p_EE(3,:,:),                    &
!     &                jmax2*kmax2,MPI_REAL4,          &
!     &                nworker-1,0,MPI_COMM_WORLD,ierr)
!                    ! EE(im+1,j,k) in serial code
!        call MPI_RECV(p_EE(p_ie_g(rank),:,:),         &
!     &                jmax2*kmax2,MPI_REAL4,          &
!     &                        0,0,MPI_COMM_WORLD,status,ierr)
!
!!     im = imax1
!!     EE(1,j,k)    = EE(im,j,k)
!! 180 EE(im+1,j,k) = EE(2,j,k)
!! 180 EE(p_ie_o(rank),j,k) = EE(p_imax2(rank),j,k)
!
!      jm = jmax1
!!     EE(i,1,k)    = EE(i,jm,k)
!  200 p_EE(i,jm+1,k) = p_EE(i,2,k)


      ! Update buffer at last
      call UPDATE_BUFFER_REAL(p_EE) 

      return
      end if
  220 continue
      return 

      end



cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_coefD
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  calculate the coefficients of the finite difference
c  equation for the temperature equation
!----------------------------------------------------------------------!
      use moment_dim
      use common_mpi
!----------------------------------------------------------------------!

      p_visdd(:,:,:) = ( p_vis(:,:,:))/sigD
      p_al(:,:,:) = 0.
      p_ah(:,:,:) = 0.
      p_as(:,:,:) = 0.
      p_an(:,:,:) = 0.
      p_aw(:,:,:) = 0.
      p_ae(:,:,:) = 0.

      do 200 k=2,kmax1
      do 200 j=p_is_o(rank),p_ie_o(rank)
      do 200 i=2,imax1 ! 2~imax1

      if(p_ijc(i,j,k).eq.0) go to 200

      if(p_ijc(i,j,k-1).eq.0) then
      dlzm = 0.5*dz(k)
      else
      dlzm = delz(k-1)
      end if

      if(p_ijc(i,j,k+1).eq.0) then
      dlzp = 0.5*dz(k)
      else
      dlzp = delz(k)
      end if

      if(p_ijc(i-1,j,k).eq.0) then
      dlxm = 0.5*dx(i)
      else
      dlxm = delx(i-1)
      end if

      if(p_ijc(i+1,j,k).eq.0) then
      dlxp = 0.5*dx(i)
      else
      dlxp = delx(i)
      end if

      if(p_ijc(i,j-1,k).eq.0) then
      dlym = 0.5*p_dy(j)
      else
      dlym = p_dely(j-1)
      end if

      if(p_ijc(i,j+1,k).eq.0) then
      dlyp = 0.5*p_dy(j)
      else
      dlyp = p_dely(j)
      end if

      dl  = (dz(k)*p_visdd(i,j,k-1)+dz(k-1)*p_visdd(i,j,k))
     .      /((dz(k-1)+dz(k))*dlzm)
      den = (p_dena(i,j,k-1)+p_dena(i,j,k-1)
     .      +p_dena(i,j,k  )+p_dena(i,j,k  ))/4.
      fz  = den*p_ww(i,j,k-1)
      p_al(i,j,k) = dx(i)*p_dy(j)
     .            *(dl*amax1(0.,(1.-0.1*abs(fz)/dl)**5)+amax1(fz,0.))
     .            *p_afsc(i,j,k)

      ds  = (p_dy(j)*p_visdd(i,j-1,k)+p_dy(j-1)*p_visdd(i,j,k))
     .      /((p_dy(j-1)+p_dy(j))*dlym)
      den = (p_dena(i,j-1,k)+p_dena(i,j-1,k)
     .      +p_dena(i,j  ,k)+p_dena(i,j  ,k))/4.
      fy  = den*p_vv(i,j-1,k)
      p_as(i,j,k) = dx(i)*dz(k)
     .            *(ds*amax1(0.,(1.-0.1*abs(fy)/ds)**5)+amax1(fy,0.))
     .            *p_afsb(i,j-1,k)

      dw  = (dx(i)*p_visdd(i-1,j,k)+dx(i-1)*p_visdd(i,j,k))
     .      /((dx(i-1)+dx(i))*dlxm)
      den = (p_dena(i-1,j,k)+p_dena(i-1,j,k)
     .      +p_dena(i  ,j,k)+p_dena(i  ,j,k))/4.
      fx  = den*p_uu(i-1,j,k)
      p_aw(i,j,k) = p_dy(j)*dz(k)
     .            *(dw*amax1(0.,(1.-0.1*abs(fx)/dw)**5)+amax1(fx,0.))
     .            *p_afsa(i,j,k)
  
      de  = (dx(i+1)*p_visdd(i,j,k)+dx(i)*p_visdd(i+1,j,k))
     .      /((dx(i)+dx(i+1))*dlxp)
      den = (p_dena(i  ,j,k)+p_dena(i  ,j,k)
     .      +p_dena(i+1,j,k)+p_dena(i+1,j,k))/4.
      fx  = den*p_uu(i,j,k)
      p_ae(i,j,k) = p_dy(j)*dz(k)
     .            *(de*amax1(0.,(1.-0.1*abs(fx)/de)**5)+amax1(0.,-fx))
     .            *p_afsa(i+1,j,k)

      dn  = (p_dy(j+1)*p_visdd(i,j,k)+p_dy(j)*p_visdd(i,j+1,k))
     .      /((p_dy(j)+p_dy(j+1))*dlyp)
      den = (p_dena(i,j  ,k)+p_dena(i,j  ,k)
     .      +p_dena(i,j+1,k)+p_dena(i,j+1,k))/4.
      fy  = den*p_vv(i,j,k)
      p_an(i,j,k) = dx(i)*dz(k)
     .            *(dn*amax1(0.,(1.-0.1*abs(fy)/dn)**5)+amax1(0.,-fy))
     .            *p_afsb(i,j,k)

      dh  = (dz(k+1)*p_visdd(i,j,k)+dz(k)*p_visdd(i,j,k+1))
     .      /((dz(k)+dz(k+1))*dlzp)
      den = (p_dena(i,j,k  )+p_dena(i,j,k  )
     .      +p_dena(i,j,k+1)+p_dena(i,j,k+1))/4.
      fz  = den*p_ww(i,j,k)
      p_ah(i,j,k) = dx(i)*p_dy(j)
     .            *(dh*amax1(0.,(1.-0.1*abs(fz)/dh)**5)+amax1(0.,-fz))
     .            *p_afsc(i,j,k+1)


      if(ither.eq.1) then

      if(p_ijc(i,j,k-1).eq.1) then
      t1 = (dz(k  )*p_tt(i,j,k+1)+dz(k+1)*p_tt(i,j,k  ))/(dz(k)+dz(k+1))
      t2 = (dz(k-1)*p_tt(i,j,k  )+dz(k  )*p_tt(i,j,k-1))/(dz(k-1)+dz(k))
      dtdz = (t1-t2)/dz(k)
      else
      t1 = (dz(k  )*p_tt(i,j,k+1)+dz(k+1)*p_tt(i,j,k  ))/(dz(k)+dz(k+1))
      dtdz = (t1 - p_tt(i,j,k))/(0.5*dz(k))
      endif 

      else
      dtdz = 0.
      endif

      if(irun.eq.1) then
        c_eta = p_EE(i,j,k)/p_DDo(i,j,k)*p_diff(i,j,k)**0.5
        c_rng = c2 + cu*c_eta**3.*(1.-c_eta/4.377)/(1.+0.012*c_eta**3)
      else
        c_rng = c2
      endif

      p_scD(i,j,k) = c1*p_dena(i,j,k)*p_DDo(i,j,k)
     .                   /p_EE(i,j,k)*p_vis(i,j,k)
     .                *(p_diff(i,j,k)-gravity*dtdz/(p_ref(i,j,k)*Prt))
     .           -c_rng*p_dena(i,j,k)*p_DDo(i,j,k)**2/p_EE(i,j,k)

      p_apDD(i,j,k) = p_denao(i,j,k)*dx(i)*p_dy(j)*dz(k)
     .             *p_afsv(i,j,k)/delt+
     .  p_ae(i,j,k)+p_aw(i,j,k)+p_an(i,j,k)+p_as(i,j,k)
     .             +p_ah(i,j,k)+p_al(i,j,k)
     
      p_s(i,j,k) = p_denao(i,j,k)*dx(i)*p_dy(j)*dz(k)
     .          *p_afsv(i,j,k)*p_DDo(i,j,k)/delt
     .          + p_scD(i,j,k)*dx(i)*p_dy(j)*dz(k)*p_afsv(i,j,k)
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c Drag force by trees

      IF (itree .eq. 1) then ! HJ tree
      IF (p_itc(i,j,k) .eq. 0) then
      tu = (p_uu(i-1,j,k)+p_uu(i,j,k))/2.
      tv = (p_vv(i,j-1,k)+p_vv(i,j,k))/2.
      tw = (p_ww(i,j,k-1)+p_ww(i,j,k))/2.

      vel  = sqrt(tu**2.+tv**2.+tw**2.)
      p_spDp(i,j,k) = -6.0*p_dena(i,j,k)
     .              *p_cdrag(i,j,k)*p_tfrac(i,j,1)*p_dleaf(i,j,1)*vel
      p_spDu(i,j,k) = (3./2.)*p_dena(i,j,k)*p_DDo(i,j,k)/p_EE(i,j,k)
     .             *p_cdrag(i,j,k)*p_tfrac(i,j,1)*p_dleaf(i,j,1)*vel**3.

      p_s(i,j,k) = p_s(i,j,k) + p_spDu(i,j,k)
      p_apDD(i,j,k) = p_apDD(i,j,k) - p_spDp(i,j,k)
      end if
      endif
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
  200 continue
 
c  implement boundary conditions

c  at the lower boundary 
      do 220 j=p_is_o(rank),p_ie_o(rank)
      do 220 i=2,imax1 ! 2~imax1

      if(p_ijc(i,j,2).ne.0) then
      c_sp = cu**0.75*p_EE(i,j,2)**1.5/tkapa
      p_spD(i,j,2) = -1.E30
      p_swD(i,j,2) = c_sp*p_dena(i,j,2)*2./dz(2)*1.E30
      p_apDD(i,j,2) = p_apDD(i,j,2) - p_spD(i,j,2)
c     s(i,j,2) = p_swD(i,j,2)
      p_s(i,j,2) = p_s(i,j,2) + p_swD(i,j,2)
c     s(i,j,2) = p_denao(i,j,2)*dx(i)*dy(j)*dz(2)*DDo(i,j,2)/delt
c    .         + p_swD(i,j,2)
      p_al(i,j,2) = 0.
      endif

  220 continue

c  at the top of the model (shear-free condition)
      do 240 j=p_is_o(rank),p_ie_o(rank)
      do 240 i=2,imax1 ! 2~imax1
      p_apDD(i,j,kmax1) = p_apDD(i,j,kmax1)-p_ah(i,j,kmax1)
      p_ah(i,j,kmax1)   = 0.
  240 continue

c  at the top of the buildings 
      do 260 k=3,kmax1
      do 260 j=p_is_o(rank),p_ie_o(rank)
      do 260 i=2,imax1 ! 2~imax1

      if((p_ijc(i,j,k).eq.1).and.(p_ijc(i,j,k-1).eq.0)) then
      c_sp = cu**0.75*p_EE(i,j,k)**1.5/tkapa
      p_spD(i,j,k) = -1.E30*(1.-p_afsc(i,j,k))
      p_swD(i,j,k) = c_sp*p_dena(i,j,k)*2./dz(k)*1.E30
     .            *(1.-p_afsc(i,j,k))
      p_apDD(i,j,k) = p_apDD(i,j,k) - p_spD(i,j,k)
c     s(i,j,k) = p_swD(i,j,k)
      p_s(i,j,k) = p_s(i,j,k) + p_swD(i,j,k)
c     s(i,j,k) = p_denao(i,j,k)*dx(i)*dy(j)*dz(k)*DDo(i,j,k)/delt
c    .         + p_swD(i,j,k)
      endif
   
      if((p_ijc(i,j,k).eq.1).and.(p_ijc(i,j,k+1).eq.0)) then
      c_sp = cu**0.75*p_EE(i,j,k)**1.5/tkapa
      p_spD(i,j,k) = -1.E30*(1.-p_afsc(i,j,k+1))
      p_swD(i,j,k) = c_sp*p_dena(i,j,k)*2./dz(k)*1.E30
     .            *(1.-p_afsc(i,j,k+1))
      p_apDD(i,j,k) = p_apDD(i,j,k) - p_spD(i,j,k)
c     s(i,j,k) = p_swD(i,j,k)
      p_s(i,j,k) = p_s(i,j,k) + p_swD(i,j,k)
c     s(i,j,k) = p_denao(i,j,k)*dx(i)*dy(j)*dz(k)*DDo(i,j,k)/delt
c    .         + p_swD(i,j,k)
      endif

      if(p_ijc(i,j,k).eq.2) then
      c_sp = cu**0.75*p_EE(i,j,k)**1.5/tkapa
      p_spD(i,j,k) = -1.E30*abs(p_afsc(i,j,k+1)-p_afsc(i,j,k))
      p_swD(i,j,k) = c_sp*p_dena(i,j,k)*2./dz(k)*1.E30
     .            *abs(p_afsc(i,j,k+1)-p_afsc(i,j,k))
      p_apDD(i,j,k) = p_apDD(i,j,k) - p_spD(i,j,k)
      p_s(i,j,k) = p_s(i,j,k) + p_swD(i,j,k)
      endif

  260 continue

c  at the building walls 
      do 280 k=2,kmax1
      do 280 j=p_is_o(rank),p_ie_o(rank)
      do 280 i=2,imax1 ! 2~imax1

      if(p_ijc(i,j,k).eq.1) then

      if(p_ijc(i-1,j,k).eq.0) then
      c_sp = cu**0.75*p_EE(i,j,k)**1.5/tkapa
      p_spD(i,j,k) = -1.E30*(1.-p_afsa(i,j,k))
      p_swD(i,j,k) = c_sp*p_dena(i,j,k)*2./dx(i)*1.E30
     .            *(1.-p_afsa(i,j,k))
      p_apDD(i,j,k) = p_apDD(i,j,k) - p_spD(i,j,k)
c     s(i,j,k) = p_swD(i,j,k)
      p_s(i,j,k) = p_s(i,j,k) + p_swD(i,j,k)
c     s(i,j,k) = p_denao(i,j,k)*dx(i)*dy(j)*dz(k)*DDo(i,j,k)/delt
c    .         + p_swD(i,j,k)
      endif

      if(p_ijc(i+1,j,k).eq.0) then
      c_sp = cu**0.75*p_EE(i,j,k)**1.5/tkapa
      p_spD(i,j,k) = -1.E30*(1.-p_afsa(i+1,j,k))
      p_swD(i,j,k) = c_sp*p_dena(i,j,k)*2./dx(i)*1.E30
     .            *(1.-p_afsa(i+1,j,k))
      p_apDD(i,j,k) = p_apDD(i,j,k) - p_spD(i,j,k)
c     s(i,j,k) = p_swD(i,j,k)
      p_s(i,j,k) = p_s(i,j,k) + p_swD(i,j,k)
c     s(i,j,k) = p_denao(i,j,k)*dx(i)*dy(j)*dz(k)*DDo(i,j,k)/delt
c    .         + p_swD(i,j,k)
      endif

      if(p_ijc(i,j-1,k).eq.0) then
      c_sp = cu**0.75*p_EE(i,j,k)**1.5/tkapa
      p_spD(i,j,k) = -1.E30*(1.-p_afsb(i,j-1,k))
      p_swD(i,j,k) = c_sp*p_dena(i,j,k)*2./p_dy(j)*1.E30
     .            *(1.-p_afsb(i,j-1,k))
      p_apDD(i,j,k) = p_apDD(i,j,k) - p_spD(i,j,k)
c     s(i,j,k) = p_swD(i,j,k)
      p_s(i,j,k) = p_s(i,j,k) + p_swD(i,j,k)
c     s(i,j,k) = p_denao(i,j,k)*dx(i)*dy(j)*dz(k)*DDo(i,j,k)/delt
c    .         + p_swD(i,j,k)
      endif

      if(p_ijc(i,j+1,k).eq.0) then
      c_sp = cu**0.75*p_EE(i,j,k)**1.5/tkapa
      p_spD(i,j,k) = -1.E30*(1.-p_afsb(i,j,k))
      p_swD(i,j,k) = c_sp*p_dena(i,j,k)*2./p_dy(j)*1.E30
     .            *(1.-p_afsb(i,j,k))
      p_apDD(i,j,k) = p_apDD(i,j,k) - p_spD(i,j,k)
c     s(i,j,k) = p_swD(i,j,k)
      p_s(i,j,k) = p_s(i,j,k) + p_swD(i,j,k)
c     s(i,j,k) = p_denao(i,j,k)*dx(i)*dy(j)*dz(k)*DDo(i,j,k)/delt
c    .         + p_swD(i,j,k)
      endif
      end if

      if(p_ijc(i,j,k).eq.2) then
      c_sp = cu**0.75*p_EE(i,j,k)**1.5/tkapa
      p_spD(i,j,k) = -1.E30*abs(p_afsa(i+1,j,k)-p_afsa(i,j,k))
      p_swD(i,j,k) = c_sp*p_dena(i,j,k)*2./dx(i)*1.E30
     .            *abs(p_afsa(i+1,j,k)-p_afsa(i,j,k))
      p_apDD(i,j,k) = p_apDD(i,j,k) - p_spD(i,j,k)
      p_s(i,j,k) = p_s(i,j,k) + p_swD(i,j,k)

      p_spD(i,j,k) = -1.E30*abs(p_afsb(i,j,k)-p_afsb(i,j-1,k))
      p_swD(i,j,k) = c_sp*p_dena(i,j,k)*2./p_dy(j)*1.E30
     .            *abs(p_afsb(i,j,k)-p_afsb(i,j-1,k))
      p_apDD(i,j,k) = p_apDD(i,j,k) - p_spD(i,j,k)
      p_s(i,j,k) = p_s(i,j,k) + p_swD(i,j,k)
      endif

  280 continue

c  at the horizontp_al boundaries
c  x = 0
c  shear-free or outflow conditions?


      do 320 k=2,kmax1
      do 320 j=p_is_o(rank),p_ie_o(rank)
      if((infw(1,j,k).eq.0).or.(infw(1,j,k).eq.2)) then
      if(p_ijc(2,j,k).ne.0) then
      p_apDD(2,j,k) = p_apDD(2,j,k)-p_aw(2,j,k)
        p_aw(2,j,k) = 0.
      end if
      end if
  320 continue
c  inflow conditions?
      do 340 k=2,kmax1
      do 340 j=p_is_o(rank),p_ie_o(rank)
      if(infw(1,j,k).eq.1) then
      if(p_ijc(2,j,k).ne.0) then
       p_s(2,j,k) = p_s(2,j,k)+p_DD(1,j,k)*p_aw(2,j,k)
      p_aw(2,j,k) = 0.              !iss!
      end if
      end if
  340 continue



c  x = xmax
c  shear-free or outflow conditions?


      do 360 k=2,kmax1
      do 360 j=p_is_o(rank),p_ie_o(rank)
      if((infe(imax2,j,k).eq.0).or.(infe(imax2,j,k).eq.2)) then
      if(p_ijc(imax1,j,k).ne.0) then
      p_apDD(imax1,j,k) = p_apDD(imax1,j,k)-p_ae(imax1,j,k)
        p_ae(imax1,j,k) = 0.
      end if
      end if
  360 continue
c  inflow conditions?
      do 380 k=2,kmax1
      do 380 j=p_is_o(rank),p_ie_o(rank)
      if(infe(imax2,j,k).eq.1) then
      if(p_ijc(imax1,j,k).ne.0) then
       p_s(imax1,j,k) = p_s(imax1,j,k)+p_DD(imax2,j,k)*p_ae(imax1,j,k)
      p_ae(imax1,j,k) = 0.              !iee!
      end if
      end if
  380 continue



c  y = 0
c  shear-free or outflow conditions?

      if ( rank == 0 ) then ! WORKER 1 only for x = 0 ##################
      is   = p_is_o(rank) ! = 2
      iss  = p_is_g(rank) ! = 1
      do 400 k=2,kmax1
      do 400 i=2,imax1 ! 2~imax1
      if((infs(i,iss,k).eq.0).or.(infs(i,iss,k).eq.2)) then
      if(p_ijc(i,is,k).ne.0) then
      p_apDD(i,is,k) = p_apDD(i,is,k)-p_as(i,is,k)
        p_as(i,is,k) = 0.
      end if
      end if
  400 continue
c  inflow conditions?
      do 420 k=2,kmax1
      do 420 i=2,imax1 ! 2~imax1
      if(infs(i,iss,k).eq.1) then
      if(p_ijc(i,is,k).ne.0) then
       p_s(i,is,k) = p_s(i,is,k)+p_DD(i,iss,k)*p_as(i,is,k)
      p_as(i,is,k) = 0.
      end if
      end if
  420 continue
      end if

c  y = ymax
      if ( rank == nworker-1 ) then ! WORKER nworker only for x = xmax ###
      ie   = p_ie_o(rank)  ! = imax1
      iee  = p_imax1(rank) ! = imax2
      do 440 k=2,kmax1
      do 440 i=2,imax1 ! 2~imax1
      if((infn(i,iee,k).eq.0).or.(infn(i,iee,k).eq.2)) then
      if(p_ijc(i,ie,k).ne.0) then
      p_apDD(i,ie,k) = p_apDD(i,ie,k)-p_an(i,ie,k)
        p_an(i,ie,k) = 0.
      end if
      end if
  440 continue
c  inflow conditions?
      do 460 k=2,kmax1
      do 460 i=2,imax1 ! 2~imax1
      if(infn(i,iee,k).eq.1) then
      if(p_ijc(i,ie,k).ne.0) then
       p_s(i,ie,k) = p_s(i,ie,k)+p_DD(i,iee,k)*p_an(i,ie,k)
      p_an(i,ie,k) = 0.
      end if
      end if
  460 continue
      end if      
      return

      end


cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_sorDD
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  successive overrelaxation with the relaxation parameter omega.
!----------------------------------------------------------------------!      
      use moment_dim
      use common_mpi
      !----------------------------------------------------------------!      
      real :: resid,anorm,anorm_sum
      integer :: i,j,k,im,jm,n,ibdy
!----------------------------------------------------------------------!      
     
      do 220 n=1,maxits

      p_dum(:,:,:) = 0.0

      call UPDATE_BUFFER_REAL(p_DD)

      anorm = 0. ; anorm_sum = 0.
      if(mod(n,2).eq.0) then
      do 120 k=2,kmax1
      do 120 j=p_is_o(rank),p_ie_o(rank)
      do 120 i=2,imax1 ! 2~imax1
  120 p_dum(i,j,k) = p_DD(i,j,k)
      end if

      do 140 k=2,kmax1
      do 140 j=p_is_o(rank),p_ie_o(rank)
      do 140 i=2,imax1 ! 2~imax1
      if(p_ijc(i,j,k).eq.0) go to 140
      if(p_odevn(i,j,k).eq.mod(n,2)) then
      resid =- p_s(i,j,k)
     .       -p_al(i,j,k)*p_DD(i  ,j  ,k-1)
     .       -p_as(i,j,k)*p_DD(i  ,j-1,k  )
     .       -p_aw(i,j,k)*p_DD(i-1,j  ,k  )
     .       -p_ah(i,j,k)*p_DD(i  ,j  ,k+1)
     .       -p_an(i,j,k)*p_DD(i  ,j+1,k  )
     .       -p_ae(i,j,k)*p_DD(i+1,j  ,k  )
     .     +p_apDD(i,j,k)*p_DD(i  ,j  ,k  )
      p_DD(i,j,k) = p_DD(i,j,k)-omegag*resid/p_apDD(i,j,k)
      end if
      if(p_DD(i,j,k).lt.1.E-10) p_DD(i,j,k) = 1.E-10
  140 continue

c  convergence test
      if(mod(n,2).eq.0) then
      do 160 k=2,kmax1
                                          !          p_ie_u
      do 160 j=p_is_o(rank),p_ie_o(rank)
      do 160 i=2,imax
      if(p_ijc(i,j,k).eq.0) go to 160
      if(abs(p_DD(i,j,k)).lt.cutD) go to 160
      anorm = anorm+abs((p_DD(i,j,k)-p_dum(i,j,k))/p_DD(i,j,k))
  160 continue
      anorm = anorm/float(itotal)

      call MPI_ALLREDUCE(anorm,anorm_sum,1,MPI_REAL,
     .                   MPI_SUM,MPI_COMM_WORLD,ierr)

      end if
      if(n.gt.1.and.(anorm_sum.lt.Dbmin)) then

! Will be parallelized !!!!!!!!!!!
!                    ! DD(2,j,k) in serial code
!        call MPI_SEND(p_DD(3,:,:),                    &
!     &                jmax2*kmax2,MPI_REAL4,          &
!!     &                nworker-1,0,MPI_COMM_WORLD,ierr)
!                    ! DD(im+1,j,k) in serial code
!        call MPI_RECV(p_DD(p_ie_g(rank),:,:),         &
!     &                jmax2*kmax2,MPI_REAL4,          &
!     &                        0,0,MPI_COMM_WORLD,status,ierr)
!!     im = imax1
!!     jm = jmax1
!!     DD(1,j,k)    = DD(im,j,k)
!! 180 DD(im+1,j,k) = DD(2,j,k)
!
!!     DD(i,1,k)    = DD(i,jm,k)
!  200 p_DD(i,jm+1,k) = p_DD(i,2,k)
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

      ! Update buffer at last
      call UPDATE_BUFFER_REAL(p_DD)
      return
      end if
  220 continue


      return 

      end


ccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_coefp
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  cp_alculate the coefficients of the finite difference
c  equation for the pressure equation
!----------------------------------------------------------------------!      
      use moment_dim
      use common_mpi
!----------------------------------------------------------------------!      

!      call UPDATE_BUFFER_REAL(p_apx)  !--> Possible to remove ?
      call UPDATE_BUFFER_REAL(p_apy)  !--> Possible to remove ?
     
      p_al(:,:,:) = 0.
      p_ah(:,:,:) = 0.
      p_as(:,:,:) = 0.
      p_an(:,:,:) = 0.
      p_aw(:,:,:) = 0.
      p_ae(:,:,:) = 0.

      do 200 k=2,kmax1
      do 200 j=p_is_o(rank),p_ie_o(rank)
      do 200 i=2,imax1 ! 2~imax1
      if(p_ijc(i,j,k).eq.0) go to 200
      denxp = (p_dena(i  ,j  ,k  )+p_dena(i+1,j  ,k  ))/2.
      p_ae(i,j,k) = denxp*(p_dy(j)*dz(k)*p_afsa(i+1,j,k))
     .           **2/p_apx(i  ,j  ,k  )
      denxm = (p_dena(i-1,j  ,k  )+p_dena(i  ,j  ,k  ))/2.
      p_aw(i,j,k) = denxm*(p_dy(j)*dz(k)*p_afsa(i,j,k))
     .           **2/p_apx(i-1,j  ,k  )
      denyp = (p_dena(i  ,j  ,k  )+p_dena(i  ,j+1,k  ))/2.
      p_an(i,j,k) = denyp*(dx(i)*dz(k)*p_afsb(i,j,k))
     .           **2/p_apy(i  ,j  ,k  )
      denym = (p_dena(i  ,j-1,k  )+p_dena(i  ,j  ,k  ))/2.
      p_as(i,j,k) = denym*(dx(i)*dz(k)*p_afsb(i,j-1,k))
     .           **2/p_apy(i  ,j-1,k  )
      denzp = (p_dena(i  ,j  ,k  )+p_dena(i  ,j  ,k+1))/2.
      p_ah(i,j,k) = denzp*(dx(i)*p_dy(j)*p_afsc(i,j,k+1))
     .           **2/p_apz(i  ,j  ,k  )
      denzm = (p_dena(i  ,j  ,k-1)+p_dena(i  ,j  ,k  ))/2.
      p_al(i,j,k) = denzm*(dx(i)*p_dy(j)*p_afsc(i,j,k))
     .           **2/p_apz(i  ,j  ,k-1)
  200 continue

c  implement boundary conditions
c  at the lower boundary 
      do 220 j=p_is_o(rank),p_ie_o(rank)
      do 220 i=2,imax1 ! 2~imax1
      if(p_ijc(i,j,2).ne.0) p_al(i,j,2)=0.
  220 continue

c  at the upper boundary (shear-free flow)
      do 240 j=p_is_o(rank),p_ie_o(rank)
      do 240 i=2,imax1 ! 2~imax1
      p_ah(i,j,kmax1) = 0.
  240 continue

c  at the building top 
      do 260 k=3,kmax1
      do 260 j=p_is_o(rank),p_ie_o(rank)
      do 260 i=2,imax1 ! 2~imax1
      if((p_ijc(i,j,k).ne.0).and.(p_ijc(i,j,k-1).eq.0)) p_al(i,j,k)=0.
      if((p_ijc(i,j,k).ne.0).and.(p_ijc(i,j,k+1).eq.0)) p_ah(i,j,k)=0.
  260 continue

c  at the building walls 
      do 280 k=2,kmax1
      do 280 j=p_is_o(rank),p_ie_o(rank)
      do 280 i=2,imax1
      if(p_ijc(i,j,k).eq.0) go to 280
      if(p_ijc(i-1,j,k).eq.0) p_aw(i,j,k)=0.
      if(p_ijc(i+1,j,k).eq.0) p_ae(i,j,k)=0.
      if(p_ijc(i,j-1,k).eq.0) p_as(i,j,k)=0.
      if(p_ijc(i,j+1,k).eq.0) p_an(i,j,k)=0.
  280 continue

c  implement boundary conditions


c  x = 0
      do 320 k=2,kmax1
      do 320 j=p_is_o(rank),p_ie_o(rank)
      if(p_ijc(2,j,k).ne.0) p_aw(2,j,k)=0.
  320 continue
c  outflow conditions?
      do 340 k=2,kmax1
      do 340 j=p_is_o(rank),p_ie_o(rank)
      if(infw(1,j,k).eq.2) then
      if(p_ijc(2,j,k).ne.0) p_ae(2,j,k)=0.
      end if
  340 continue



c  x = xmax
      do 360 k=2,kmax1
      do 360 j=p_is_o(rank),p_ie_o(rank)
      if(p_ijc(imax1,j,k).ne.0) p_ae(imax1,j,k)=0.
  360 continue
c  outflow conditions?
      do 380 k=2,kmax1
      do 380 j=p_is_o(rank),p_ie_o(rank)
      if(infe(imax2,j,k).eq.2) then
      if(p_ijc(imax1,j,k).ne.0) p_aw(imax1,j,k)=0.
      end if
  380 continue


c  y = 0
      if ( rank == 0 ) then ! WORKER 1 only for x = 0 ##################
      is  = p_is_o(rank) ! = 2
      iss  = p_is_g(rank) ! = 1
      do 440 k=2,kmax1
      do 440 i=2,imax1 ! 2~imax1
      if(p_ijc(i,is,k).ne.0) p_as(i,is,k)=0.
  440 continue
c  outflow conditions?
      do 460 k=2,kmax1
      do 460 i=2,imax1 ! 2~imax1
      if(infs(i,iss,k).eq.2) then
      if(p_ijc(i,is,k).ne.0) p_an(i,is,k)=0.
      end if
  460 continue
      end if

c  y = ymax
      if ( rank == nworker-1 ) then ! WORKER nworker only for x = xmax ###
      ie   = p_ie_o(rank)  ! = imax1
      iee  = p_imax1(rank) ! = imax2
      do 500 k=2,kmax1
      do 500 i=2,imax1 ! 2~imax1
      if(p_ijc(i,ie,k).ne.0) p_an(i,ie,k)=0.
  500 continue
c  outflow conditions?
      do 520 k=2,kmax1
      do 520 i=2,imax1 ! 2~imax1
      if(infn(i,iee,k).eq.2) then
      if(p_ijc(i,ie,k).ne.0) p_as(i,ie,k)=0.
      end if
  520 continue
      endif
      
      do 620 k=2,kmax1
      do 620 j=p_is_o(rank),p_ie_o(rank)
      do 620 i=2,imax1
      if(p_ijc(i,j,k).eq.0) go to 620
      denxp = (p_dena(i  ,j  ,k  )+p_dena(i+1,j  ,k  ))/2.
      denxm = (p_dena(i-1,j  ,k  )+p_dena(i  ,j  ,k  ))/2.
      denyp = (p_dena(i  ,j  ,k  )+p_dena(i  ,j+1,k  ))/2.
      denym = (p_dena(i  ,j-1,k  )+p_dena(i  ,j  ,k  ))/2.
      denzp = (p_dena(i  ,j  ,k  )+p_dena(i  ,j  ,k+1))/2.
      denzm = (p_dena(i  ,j  ,k-1)+p_dena(i  ,j  ,k  ))/2.
      p_app(i,j,k) = p_ae(i,j,k)+p_aw(i,j,k)+p_an(i,j,k)+
     .               p_as(i,j,k)+p_ah(i,j,k)+p_al(i,j,k)
      p_s(i,j,k) = (p_denao(i,j,k)-p_dena(i,j,k))
     .             *dx(i)*p_dy(j)*dz(k)*p_afsv(i,j,k)/delt
     .          +(denxm*p_uu(i-1,j,k)*p_afsa(i,j,k)
     .          - denxp*p_uu(i,j,k)*p_afsa(i+1,j,k))*p_dy(j)*dz(k)
     .          +(denym*p_vv(i,j-1,k)*p_afsb(i,j-1,k)
     .          - denyp*p_vv(i,j,k)*p_afsb(i,j,k))*dx(i)*dz(k)
     .          +(denzm*p_ww(i,j,k-1)*p_afsc(i,j,k)
     .          - denzp*p_ww(i,j,k)*p_afsc(i,j,k+1))*dx(i)*p_dy(j)
  620 continue
      return

      end



cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_coefc                                               
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  calculate the coefficients of the finite difference
c  equation for the temperature equation
!----------------------------------------------------------------------!      
      use moment_dim
      use common_mpi
!----------------------------------------------------------------------!      

      p_gam(:,:,:) = p_vis(:,:,:)/Sct
      p_al(:,:,:) = 0.
      p_ah(:,:,:) = 0.
      p_as(:,:,:) = 0.
      p_an(:,:,:) = 0.
      p_aw(:,:,:) = 0.
      p_ae(:,:,:) = 0.

      do 200 k=2,kmax1
      do 200 j=p_is_o(rank),p_ie_o(rank)
      do 200 i=2,imax1
      if(p_ijc(i,j,k).eq.0) go to 200

      if(p_ijc(i,j,k-1).eq.0) then
      dlzm = 0.5*dz(k)
      else
      dlzm = delz(k-1)
      end if

      if(p_ijc(i,j,k+1).eq.0) then
      dlzp = 0.5*dz(k)
      else
      dlzp = delz(k)
      end if

      if(p_ijc(i-1,j,k).eq.0) then
      dlxm = 0.5*dx(i)
      else
      dlxm = delx(i-1)
      end if

      if(p_ijc(i+1,j,k).eq.0) then
      dlxp = 0.5*dx(i)
      else
      dlxp = delx(i)
      end if

      if(p_ijc(i,j-1,k).eq.0) then
      dlym = 0.5*p_dy(j)
      else
      dlym = p_dely(j-1)
      end if

      if(p_ijc(i,j+1,k).eq.0) then
      dlyp = 0.5*p_dy(j)
      else
      dlyp = p_dely(j)
      end if

      dl  = (dz(k)*p_gam(i,j,k-1)+dz(k-1)*p_gam(i,j,k))
     .      /((dz(k-1)+dz(k))*dlzm)
      den = (p_dena(i,j,k-1)+p_dena(i,j,k-1)
     .      +p_dena(i,j,k  )+p_dena(i,j,k  ))/4.
      fz  = den*p_ww(i,j,k-1)
      p_al(i,j,k) = dx(i)*p_dy(j)*(dl*amax1(0.,(1.-0.1*abs(fz)/dl)**5)+
     .  amax1(fz,0.))*p_afsc(i,j,k)

      ds  = (p_dy(j)*p_gam(i,j-1,k)+p_dy(j-1)*p_gam(i,j,k))
     .      /((p_dy(j-1)+p_dy(j))*dlym)
      den = (p_dena(i,j-1,k)+p_dena(i,j-1,k)
     .      +p_dena(i,j  ,k)+p_dena(i,j  ,k))/4.
      fy  = den*p_vv(i,j-1,k)
      p_as(i,j,k) = dx(i)*dz(k)*(ds*amax1(0.,(1.-0.1*abs(fy)/ds)**5)+
     .  amax1(fy,0.))*p_afsb(i,j-1,k)

      dw  = (dx(i)*p_gam(i-1,j,k)+dx(i-1)*p_gam(i,j,k))
     .      /((dx(i-1)+dx(i))*dlxm)
      den = (p_dena(i-1,j,k)+p_dena(i-1,j,k)
     .      +p_dena(i  ,j,k)+p_dena(i  ,j,k))/4.
      fx  = den*p_uu(i-1,j,k)
      p_aw(i,j,k) = p_dy(j)*dz(k)*(dw*amax1(0.,(1.-0.1*abs(fx)/dw)**5)+
     .  amax1(fx,0.))*p_afsa(i,j,k)

      de  = (dx(i+1)*p_gam(i,j,k)+dx(i)*p_gam(i+1,j,k))
     .      /((dx(i)+dx(i+1))*dlxp)
      den = (p_dena(  i,j,k)+p_dena(i  ,j,k)
     .      +p_dena(i+1,j,k)+p_dena(i+1,j,k))/4.
      fx  = den*p_uu(i,j,k)
      p_ae(i,j,k) = p_dy(j)*dz(k)*(de*amax1(0.,(1.-0.1*abs(fx)/de)**5)+
     .  amax1(0.,-fx))*p_afsa(i+1,j,k)

      dn  = (p_dy(j+1)*p_gam(i,j,k)+p_dy(j)*p_gam(i,j+1,k))
     .      /((p_dy(j)+p_dy(j+1))*dlyp)
      den = (p_dena(i,j  ,k)+p_dena(i,j  ,k)
     .      +p_dena(i,j+1,k)+p_dena(i,j+1,k))/4.
      fy  = den*p_vv(i,j,k)
      p_an(i,j,k) = dx(i)*dz(k)*(dn*amax1(0.,(1.-0.1*abs(fy)/dn)**5)+
     .  amax1(0.,-fy))*p_afsb(i,j,k)

      dh  = (dz(k+1)*p_gam(i,j,k)+dz(k)*p_gam(i,j,k+1))
     .      /((dz(k)+dz(k+1))*dlzp)
      den = (p_dena(i,j,k  )+p_dena(i,j,k  )
     .      +p_dena(i,j,k+1)+p_dena(i,j,k+1))/4.
      fz  = den*p_ww(i,j,k)
      p_ah(i,j,k) = dx(i)*p_dy(j)*(dh*amax1(0.,(1.-0.1*abs(fz)/dh)**5)+
     .  amax1(0.,-fz))*p_afsc(i,j,k+1)

      p_apco(i,j,k) = p_denao(i,j,k)*dx(i)*p_dy(j)*dz(k)
     .             *p_afsv(i,j,k)/delt+
     .                   p_ae(i,j,k)+p_aw(i,j,k)+p_an(i,j,k)+
     .                   p_as(i,j,k)+p_ah(i,j,k)+p_al(i,j,k)
      
      alpa       = (p_co(i,j,k)-p_coo(i,j,k))/delt
      p_s(i,j,k) = p_denao(i,j,k)*dx(i)*p_dy(j)*dz(k)
     .             *p_afsv(i,j,k)
     .             *(p_coo(i,j,k)/delt+alpa)
  200 continue

c  implement boundary conditions
c  at the lower boundary (dirichlet condition)
      do 220 j=p_is_o(rank),p_ie_o(rank)
      do 220 i=2,imax1! 2~imax1
      if(p_ijc(i,j,2).ne.0) then
      p_s(i,j,2)  = p_s(i,j,2)+p_co(i,j,1)*p_al(i,j,2)
      p_al(i,j,2) = 0.
      end if
  220 continue

c  at the top of the model (shear-free condition)
      do 240 j=p_is_o(rank),p_ie_o(rank)
      do 240 i=2,imax1 ! 2~imax1
      p_apco(i,j,kmax1) = p_apco(i,j,kmax1)-p_ah(i,j,kmax1)
      p_ah(i,j,kmax1)   = 0.
  240 continue

c  at the top of the buildings (dirichlet condition)
      do 260 k=3,kmax1
      do 260 j=p_is_o(rank),p_ie_o(rank)
      do 260 i=2,imax1 ! 2~imax1
      if((p_ijc(i,j,k).ne.0).and.(p_ijc(i,j,k-1).eq.0)) then
      p_s(i,j,k)  = p_s(i,j,k)+p_co(i,j,k-1)*p_al(i,j,k)
      p_al(i,j,k) = 0.
      end if
  260 continue

c  at the building walls (dirichlet condition)
      do 280 k=2,kmax1
      do 280 j=p_is_o(rank),p_ie_o(rank)
      do 280 i=2,imax1 ! 2~imax1
      if(p_ijc(i,j,k).eq.0) go to 280

      if(p_ijc(i-1,j,k).eq.0) then
      p_s(i,j,k)  = p_s(i,j,k)+p_co(i-1,j,k)*p_aw(i,j,k)
      p_aw(i,j,k) = 0.
      end if

      if(p_ijc(i+1,j,k).eq.0) then
      p_s(i,j,k)  = p_s(i,j,k)+p_co(i+1,j,k)*p_ae(i,j,k)
      p_ae(i,j,k) = 0.
      end if

      if(p_ijc(i,j-1,k).eq.0) then
      p_s(i,j,k)  = p_s(i,j,k)+p_co(i,j-1,k)*p_as(i,j,k)
      p_as(i,j,k) = 0.
      end if

      if(p_ijc(i,j+1,k).eq.0) then
      p_s(i,j,k)  = p_s(i,j,k)+p_co(i,j+1,k)*p_an(i,j,k)
      p_an(i,j,k) = 0.
      end if
  280 continue


c  at the horizontal boundaries
c  x = 0
c  shear-free or outflow conditions?



      do 320 k=2,kmax1
      do 320 j=p_is_o(rank),p_ie_o(rank)
      if((infw(1,j,k).eq.0).or.(infw(1,j,k).eq.2)) then
      if(p_ijc(2,j,k).ne.0) then
      p_apco(2,j,k) = p_apco(2,j,k)-p_aw(2,j,k)
      p_aw(2,j,k)   = 0.
      end if
      end if
  320 continue
c  inflow conditions?
      do 340 k=2,kmax1
      do 340 j=p_is_o(rank),p_ie_o(rank)
      if(infw(1,j,k).eq.1) then
      if(p_ijc(2,j,k).ne.0) then
      p_s(2,j,k)  = p_s(2,j,k)+p_co(1,j,k)*p_aw(2,j,k)
                                     !iss!
      p_aw(2,j,k) = 0.
      end if
      end if
  340 continue



c  x = xmax
c  shear-free or outflow conditions?


      do 360 k=2,kmax1
      do 360 j=p_is_o(rank),p_ie_o(rank)
      if((infe(imax2,j,k).eq.0).or.(infe(imax2,j,k).eq.2)) then
      if(p_ijc(imax1,j,k).ne.0) then
      p_apco(imax1,j,k) = p_apco(imax1,j,k)-p_ae(imax1,j,k)
      p_ae(imax1,j,k)   = 0.
      end if
      end if
  360 continue
c  inflow conditions?
      do 380 k=2,kmax1
      do 380 j=p_is_o(rank),p_ie_o(rank)
      if(infe(imax2,j,k).eq.1) then
      if(p_ijc(imax1,j,k).ne.0) then
      p_s(imax1,j,k)  = p_s(imax1,j,k)+p_co(imax2,j,k)*p_ae(imax1,j,k)
                                           !iee!
      p_ae(imax1,j,k) = 0.
      end if
      end if
  380 continue



c  y = 0
      if ( rank == 0 ) then ! WORKER 1 only for x = 0 ##################
      is   = p_is_o(rank) ! = 2
      iss  = p_is_g(rank) ! = 1

c  shear-free or outflow conditions?
      do 400 k=2,kmax1
      do 400 i=2,imax1 ! 2~imax1
      if((infs(i,iss,k).eq.0).or.(infs(i,iss,k).eq.2)) then
      if(p_ijc(i,is,k).ne.0) then
      p_apco(i,is,k) = p_apco(i,is,k)-p_as(i,is,k)
      p_as(i,is,k)   = 0.
      end if
      end if
  400 continue
c  inflow conditions?
      do 420 k=2,kmax1
      do 420 i=2,imax1 ! 2~imax1
      if(infs(i,iss,k).eq.1) then
      if(p_ijc(i,is,k).ne.0) then
      p_s(i,is,k)  = p_s(i,is,k)+p_co(i,iss,k)*p_as(i,is,k)
      p_as(i,is,k) = 0.
      end if
      end if
  420 continue
      end if

c  y = ymax
      if ( rank == nworker-1 ) then ! WORKER nworker only for x = xmax ###
      ie   = p_ie_o(rank)  ! = imax1
      iee  = p_imax1(rank) ! = imax2
      do 440 k=2,kmax1
      do 440 i=2,imax1 ! 2~imax1
      if((infn(i,iee,k).eq.0).or.(infn(i,iee,k).eq.2)) then
      if(p_ijc(i,ie,k).ne.0) then
      p_apco(i,ie,k) = p_apco(i,ie,k)-p_an(i,ie,k)
      p_an(i,ie,k)   = 0.
      end if
      end if
  440 continue
c  inflow conditions?
      do 460 k=2,kmax1
      do 460 i=2,imax1 ! 2~imax1
      if(infn(i,iee,k).eq.1) then
      if(p_ijc(i,ie,k).ne.0) then
      p_s(i,ie,k)  = p_s(i,ie,k)+p_co(i,iee,k)*p_an(i,ie,k)
      p_an(i,ie,k) = 0.
      end if
      end if
  460 continue
      end if

      return

      end



cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_correc
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      use moment_dim
      use common_mpi
!----------------------------------------------------------------------!      

c  dynamic pressure correction
      do 100 k=2,kmax1
      do 100 j=p_is_o(rank),p_ie_o(rank)
      do 100 i=2,imax1
      if(p_ijc(i,j,k).ne.0) p_po(i,j,k)=p_po(i,j,k)+omegap*p_pdot(i,j,k)
  100 continue

c  x-component wind velocity correction
      do 200 k=2,kmax1
      do 200 j=p_is_o(rank),p_ie_o(rank)
      do 200 i=2,imax ! 2~imax
      if(p_ija(i,j,k).ne.0) p_uu(i,j,k)=p_uu(i,j,k)+p_dy(j)*dz(k)*
     .  p_afsa(i+1,j,k)*(p_pdot(i,j,k)-p_pdot(i+1,j,k))/p_apx(i,j,k)
  200 continue

c  y-component wind velocity correction
      do 300 k=2,kmax1
      do 300 j=p_is_u(rank),p_ie_u(rank)
      do 300 i=2,imax1
      if(p_ijb(i,j,k).ne.0) p_vv(i,j,k)=p_vv(i,j,k)+dx(i)*dz(k)*
     .  p_afsb(i,j,k)*(p_pdot(i,j,k)-p_pdot(i,j+1,k))/p_apy(i,j,k)
  300 continue

c  z-component wind velocity correction
      do 400 k=2,kmax
      do 400 j=p_is_o(rank),p_ie_o(rank)
      do 400 i=2,imax1 ! 2~imax1
      if(p_ijc(i,j,k).ne.0) p_ww(i,j,k)=p_ww(i,j,k)+dx(i)*p_dy(j)*
     .  p_afsc(i,j,k+1)*(p_pdot(i,j,k)-p_pdot(i,j,k+1))/p_apz(i,j,k)
  400 continue

      call UPDATE_BUFFER_REAL(p_uu) ! Possible to remove? 
      call UPDATE_BUFFER_REAL(p_vv) ! Possible to remove?
      call UPDATE_BUFFER_REAL(p_ww) ! Possible to remove?

      return
      end



cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_convrg(error)
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      use moment_dim
      use common_mpi
!----------------------------------------------------------------------!      

      error  = 0.
      error1 = 0.
      error2 = 0.
      do 120 k=2,kmax1
      do 120 j=p_is_o(rank),p_ie_o(rank)
      do 120 i=2,imax ! 2~imax !! imax !!!!
      if(p_ija(i,j,k).ne.0) then
      if(abs(p_uu(i,j,k)).lt.1.e-4) go to 100
      fac   = p_dy(j)*dz(k)
     .      *abs((p_pdot(i,j,k)-p_pdot(i+1,j,k))/p_apx(i,j,k))
      error1 = error1+fac/abs(p_uu(i,j,k))
  100 continue
      end if
  120 continue


      error1=error1/dfloat(itotal)

      do 130 k=2,kmax1
      do 130 j=p_is_u(rank),p_ie_u(rank)
      do 130 i=2,imax1 ! 2~imax !! imax !!!!
      if(p_ijb(i,j,k).ne.0) then
      if(abs(p_vv(i,j,k)).lt.1.e-4) go to 110
      fac   = dx(i)*dz(k)
     .       *abs((p_pdot(i,j,k)-p_pdot(i,j+1,k))/p_apy(i,j,k))
      error2 = error2+fac/abs(p_vv(i,j,k))
  110 continue
      end if
  130 continue

      error2=error2/dfloat(itotal)             !HJ
 
      error=(error1+error2)/2.         !HJ


      return
      end

cccccccccccccccccccccccccccccccc

c      error = 0.
c      do 120 k=2,kmax1
c      do 120 j=2,jmax1
c      do 120 i=p_is_u(rank),p_ie_u(rank) ! 2~imax !! imax !!!!
c                                         !          p_ie_u
c      if(p_ija(i,j,k).eq.1) then
c      if(abs(p_uu(i,j,k)).lt.1.e-4) go to 100
c      fac   = p_dy(j)*dz(k)
c     .      *abs((p_pdot(i,j,k)-p_pdot(i+1,j,k))/p_apx(i,j,k))
c      error = error+fac/abs(p_uu(i,j,k))
c  100 continue
c      end if
c  120 continue
c      error=error/itotal

c      return

c      end
cccccccccccccccccccccccccccccccc

cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_update
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      use moment_dim
      use common_mpi
!----------------------------------------------------------------------!      

      ! Update buffer
!     call UPDATE_BUFFER_REAL(p_dena)
!     call UPDATE_BUFFER_REAL(p_uu)
!     call UPDATE_BUFFER_REAL(p_vv)

      call UPDATE_BUFFER_REAL(p_ww) ! Why?

!     call UPDATE_BUFFER_REAL(p_EE)
!     call UPDATE_BUFFER_REAL(p_DD)
!     call UPDATE_BUFFER_REAL(p_tt)

!     call UPDATE_BUFFER_REAL(p_co)

c  update air density
      p_denao(:,:,:) = p_dena(:,:,:)

c  update x-component wind velocity
      do 400 k=2,kmax1
      do 400 j=p_is_o(rank),p_ie_o(rank)
      do 400 i=2,imax ! 2~imax
      if(p_ija(i,j,k).ne.0) p_uuo(i,j,k) = p_uu(i,j,k)
  400 continue

c  update y-component wind velocity
      do 420 k=2,kmax1
      do 420 j=p_is_u(rank),p_ie_u(rank)
      do 420 i=2,imax1 ! 2~imax1
      if(p_ijb(i,j,k).ne.0) p_vvo(i,j,k) = p_vv(i,j,k)
  420 continue

c  update z-component wind velocity
      do 440 k=2,kmax
      do 440 j=p_is_o(rank),p_ie_o(rank)
      do 440 i=2,imax1 ! 2~imax1
      if(p_ijc(i,j,k).ne.0) p_wwo(i,j,k) = p_ww(i,j,k)
  440 continue

c  update species concentration
      if(iconc.eq.1) then
      do 500 k=2,kmax1
      do 500 j=p_is_o(rank),p_ie_o(rank)
      do 500 i=2,imax1 ! 2~imax1
      if(p_ijc(i,j,k).ne.0) then
      if(p_co(i,j,k).lt.1.e-25) p_co(i,j,k)=0.
        p_coo(i,j,k) = p_co(i,j,k)
      end if
  500 continue
      end if

c  update turbulent kinetic energy, dissipation term and temperature
      do 600 k=2,kmax1
      do 600 j=p_is_o(rank),p_ie_o(rank)
      do 600 i=2,imax1 ! 2~imax1
      if(p_ijc(i,j,k).ne.0) then
      if(p_EE(i,j,k).lt.1.e-10) p_EE(i,j,k)=1.e-10
      p_EEo(i,j,k) = p_EE(i,j,k)
      if(p_DD(i,j,k).lt.1.e-10) p_DD(i,j,k)=1.e-10
      p_DDo(i,j,k) = p_DD(i,j,k)
      if(p_tt(i,j,k).lt.1.e-10) p_tt(i,j,k)=1.e-10
      p_tto(i,j,k) = p_tt(i,j,k)
      end if

  600 continue

!!!!!!!!! update temperature at top_boundary 
      do 601 j=p_is_g(rank),p_ie_g(rank) ! paral ! j=1,jmax2
      do 601 i=1,imax2
      p_tt(i,j,kmax2)  = p_tt(i,j,kmax1)
      p_tto(i,j,kmax2) = p_tto(i,j,kmax1)
  601 continue

!---  average reference temp  ! GK_t

      if (ref_3d == 1) then

      do 702 k=1,kmax2
      do 702 j=p_is_g(rank),p_ie_g(rank) ! paral ! j=1,jmax2
      do 702 i=1,imax2
      p_ref(i,j,k) = p_tt(i,j,k)
  702 continue

      do k = 1,kmax2
      do j = p_is_g(rank),p_ie_g(rank) ! paral ! j=1,jmax2
      do i = 1,imax2
      p_sum_ref(i,j,k) = 0.
      p_ave_ref(i,j,k) = 0.
      enddo
      enddo
      enddo

      do 602 k=2,kmax1
      do 602 j=p_is_o(rank),p_ie_o(rank) ! 2~jmax1
      do 602 i=2,imax1

      num_ref = 0

       do 502 ii = i-1,i+1
       do 502 jj = j-1,j+1
        if(p_ijc(ii,jj,k).ne.0)then

         num_ref = num_ref+1
         p_sum_ref(i,j,k)=p_sum_ref(i,j,k) + p_tt(ii,jj,k)

        endif
  502 continue

       if(p_ijc(i,j,k).ne.0)then
        p_ave_ref(i,j,k) = p_sum_ref(i,j,k)/float(num_ref)
       endif

  602 continue


      do 603 k=2,kmax1
      do 603 j=p_is_o(rank),p_ie_o(rank) ! 2~jmax1 
      do 603 i=2,imax1
        p_ref(i,j,k) = p_ave_ref(i,j,k)

  603 continue

      end if

!------------------------------------------------------------
      
      return

      end

cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine boundary_update      !HJ
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      use moment_dim
      use common_mpi
      use input_mod
        integer :: idum, jdum, kdum 

      filenames = MAKE_RDAPS_PATH('boundary_',YYDD,HH+1,'_east_u.dat')
      open(unit=51, file=trim(filenames), status='old', action='read')

      filenames = MAKE_RDAPS_PATH('boundary_',YYDD,HH+1,'_east_v.dat')
      open(unit=52, file=trim(filenames), status='old', action='read')

      filenames = MAKE_RDAPS_PATH('boundary_',YYDD,HH+1,'_east_tmp.dat')
      open(unit=53, file=trim(filenames), status='old', action='read')


      filenames = MAKE_RDAPS_PATH('boundary_',YYDD,HH+1,'_south_u.dat')
      open(unit=61, file=trim(filenames), status='old', action='read')

      filenames = MAKE_RDAPS_PATH('boundary_',YYDD,HH+1,'_south_v.dat')
      open(unit=62, file=trim(filenames), status='old', action='read')

      filenames =MAKE_RDAPS_PATH('boundary_',YYDD,HH+1,'_south_tmp.dat')
      open(unit=63, file=trim(filenames), status='old', action='read')


      filenames = MAKE_RDAPS_PATH('boundary_',YYDD,HH+1,'_west_u.dat')
      open(unit=71, file=trim(filenames), status='old', action='read')

      filenames = MAKE_RDAPS_PATH('boundary_',YYDD,HH+1,'_west_v.dat')
      open(unit=72, file=trim(filenames), status='old', action='read')

      filenames = MAKE_RDAPS_PATH('boundary_',YYDD,HH+1,'_west_tmp.dat')
      open(unit=73, file=trim(filenames), status='old', action='read')


      filenames = MAKE_RDAPS_PATH('boundary_',YYDD,HH+1,'_north_u.dat')
      open(unit=81, file=trim(filenames), status='old', action='read')

      filenames = MAKE_RDAPS_PATH('boundary_',YYDD,HH+1,'_north_v.dat')
      open(unit=82, file=trim(filenames), status='old', action='read')

      filenames= MAKE_RDAPS_PATH('boundary_',YYDD,HH+1,'_north_tmp.dat')
      open(unit=83, file=trim(filenames), status='old', action='read')


      filenames = MAKE_RDAPS_PATH('top_',YYDD,HH+1,'_u.dat')
      open(unit=91, file=trim(filenames), status='old', action='read')

      filenames = MAKE_RDAPS_PATH('top_',YYDD,HH+1,'_v.dat')
      open(unit=92, file=trim(filenames), status='old', action='read')

      filenames = MAKE_RDAPS_PATH('top_',YYDD,HH+1,'_tmp.dat')
      open(unit=93, file=trim(filenames), status='old', action='read')

      do k=1 , kmax2 !EAST
      do j=1 , jmax2  
        read(51, *) idum,jdum,kdum, uu(imax2,j,k)
        read(52, *) idum,jdum,kdum, vv(imax2,j,k)
        read(53, *) idum,jdum,kdum, tt(imax2,j,k)
        tt(imax2,j,k) = CELSIUS_TO_KELVIN(tt(imax2,j,k))
      end do 
      end do


      do k=1, kmax2 !SOUTH
      do i=1, imax2
        read(61, *) idum,jdum,kdum, uu(i,1,k)
        read(62, *) idum,jdum,kdum, vv(i,1,k)
        read(63, *) idum,jdum,kdum, tt(i,1,k)
        tt(i,1,k) = CELSIUS_TO_KELVIN(tt(i,1,k))
      end do
      end do

      do k=1, kmax2 !WEST
      do j=1, jmax2
        read(71, *) idum,jdum,kdum, uu(1,j,k)
        read(72, *) idum,jdum,kdum, vv(1,j,k)
        read(73, *) idum,jdum,kdum, tt(1,j,k)
        tt(1,j,k) = CELSIUS_TO_KELVIN(tt(1,j,k))
      end do
      end do


      do k=1, kmax2 !NORTH
      do i=1, imax2
        read(81, *) idum,jdum,kdum, uu(i,jmax2,k)
        read(82, *) idum,jdum,kdum, vv(i,jmax2,k)
        read(83, *) idum,jdum,kdum, tt(i,jmax2,k)
        tt(i,jmax2,k) = CELSIUS_TO_KELVIN(tt(i,jmax2,k))
      end do
      end do

      do j=1, jmax2 !TOP
      do i=1, imax2
        read(91, *) idum,jdum,kdum, uu(i,j,kmax2)
        read(92, *) idum,jdum,kdum, vv(i,j,kmax2)
        read(93, *) idum,jdum,kdum, tt(i,j,kmax2)
        tt(i,j,kmax2) = CELSIUS_TO_KELVIN(tt(i,j,kmax2))
      end do
      end do


        close(51);close(52);close(53)
        close(61);close(62);close(63)
        close(71);close(72);close(73)
        close(81);close(82);close(83)
        close(91);close(92);close(93)

      end 




cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_soruu
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  successive overrelaxation with the relaxation parameter omega.
!----------------------------------------------------------------------!
      use moment_dim
      use common_mpi
      !----------------------------------------------------------------!
      real :: resid,anorm,anorm_sum
      integer :: i,j,k,im,jm,n,ibdy
      real(kind=8) :: stime,etime
!----------------------------------------------------------------------!

      do 220 n=1,maxits

      p_dum(:,:,:) = 0.0

!     stime=MPI_WTIME()
      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
      call UPDATE_BUFFER_REAL (p_uu)
      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!     etime=MPI_WTIME()

      anorm = 0. ; anorm_sum = 0.
      if(mod(n,2).eq.0) then
      do 120 k=2,kmax1
      do 120 j=p_is_o(rank),p_ie_o(rank)
      do 120 i=2,imax
  120 p_dum(i,j,k) = p_uu(i,j,k)
      end if

      do 140 k=2,kmax1
      do 140 j=p_is_o(rank),p_ie_o(rank)
      do 140 i=2,imax
      if(p_apx(i,j,k).eq.-fix_v)go to 140 !!add_n
      if(p_ija(i,j,k).eq.0) go to 140
      if(p_odevn(i,j,k).eq.mod(n,2)) then
      resid = -p_s(i,j,k)
     .       -p_al(i,j,k)*p_uu(i  ,j  ,k-1)
     .       -p_as(i,j,k)*p_uu(i  ,j-1,k  )
     .       -p_aw(i,j,k)*p_uu(i-1,j  ,k  )
     .       -p_ah(i,j,k)*p_uu(i  ,j  ,k+1)
     .       -p_an(i,j,k)*p_uu(i  ,j+1,k  )
     .       -p_ae(i,j,k)*p_uu(i+1,j  ,k  )
     .      +p_apx(i,j,k)*p_uu(i  ,j  ,k  )
      p_uu(i,j,k) = p_uu(i,j,k)-omegag*resid/p_apx(i,j,k)
      end if
  140 continue


c  convergence test
      if(mod(n,2).eq.0) then
      do 160 k=2,kmax1
      do 160 j=p_is_o(rank),p_ie_o(rank)
      do 160 i=2,imax
      if(p_ija(i,j,k).eq.0) go to 160
      if(abs(p_uu(i,j,k)).lt.cutu) go to 160
      anorm = anorm+abs((p_uu(i,j,k)-p_dum(i,j,k))/p_uu(i,j,k))
  160 continue
      anorm = anorm/float(itotal)

      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
      call MPI_ALLREDUCE(anorm,anorm_sum,1,MPI_REAL,
     .                   MPI_SUM,MPI_COMM_WORLD,ierr)
      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

      end if

      if(n.gt.1.and.(anorm_sum.lt.ubmin)) then

c      jm = jmax1
c      if ( rank == nworker-1 ) then
c      im = p_ie_u(rank) ! i=imax 
c      do 180 k=1,kmax2
c      do 180 j=1,jmax2
c      if(infw(1,j,k).eq.4) then
c      p_uu(2,j,k)    = p_uu(im,j,k)
c      p_uu(im+1,j,k) = p_uu(3,j,k)
c      end if
c  180 continue
c      endif
c
c      do 200 k=1,kmax2
c      do 200 i=p_is_g(rank),p_ie_g(rank) ! i=1,imax2
c      if(infs(i,1,k).eq.4) then
c      p_uu(i,1,k)    = p_uu(i,jm,k)
c      p_uu(i,jm+1,k) = p_uu(i,2,k)
c      end if
c  200 continue

      ! Update buffer at last
      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
      call UPDATE_BUFFER_REAL (p_uu)
      !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

      return
      end if

  220 continue

      return 

      end


cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_sorvv
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  successive overrelaxation with the relaxation parameter omega.
!----------------------------------------------------------------------!      
      use moment_dim
      use common_mpi
      !----------------------------------------------------------------!      
      real(kind=8) :: etime,stime
      real :: resid, anorm,anorm_sum
      integer :: i,j,k,im,jm,n
!----------------------------------------------------------------------!      

      do 220 n=1,maxits

      p_dum(:,:,:) = 0.0

!     stime=MPI_WTIME()
      call UPDATE_BUFFER_REAL(p_vv)
!     etime=MPI_WTIME()

      anorm = 0. ; anorm_sum = 0
      if(mod(n,2).eq.0) then
      do 120 k=2,kmax1
      do 120 j=p_is_u(rank),p_ie_u(rank)
      do 120 i=2,imax1 ! 2~imax1
  120 p_dum(i,j,k) = p_vv(i,j,k)
      end if

      do 140 k=2,kmax1
      do 140 j=p_is_u(rank),p_ie_u(rank)
      do 140 i=2,imax1 ! 2~imax1
      if(p_apy(i,j,k).eq.-fix_v)go to 140 !!add_n
      if(p_ijb(i,j,k).eq.0) go to 140
      if(p_odevn(i,j,k).eq.mod(n,2)) then
      resid = - p_s(i,j,k)
     .        -p_al(i,j,k)*p_vv(i  ,j  ,k-1)
     .        -p_as(i,j,k)*p_vv(i  ,j-1,k  ) 
     .        -p_aw(i,j,k)*p_vv(i-1,j  ,k  )
     .        -p_ah(i,j,k)*p_vv(i  ,j  ,k+1)
     .        -p_an(i,j,k)*p_vv(i  ,j+1,k  )
     .        -p_ae(i,j,k)*p_vv(i+1,j  ,k  )
     .       +p_apy(i,j,k)*p_vv(i  ,j  ,k  )
      p_vv(i,j,k) = p_vv(i,j,k)-omegag*resid/p_apy(i,j,k)
      end if
  140 continue

c  convergence test
      if(mod(n,2).eq.0) then
      do 160 k=2,kmax1
      do 160 j=p_is_u(rank),p_ie_u(rank)
      do 160 i=2,imax1
      if(p_ijb(i,j,k).eq.0) go to 160
      if(abs(p_vv(i,j,k)).lt.cutv) go to 160
      anorm = anorm+abs((p_vv(i,j,k)-p_dum(i,j,k))/p_vv(i,j,k))
  160 continue
      anorm = anorm/float(itotal)

      call MPI_ALLREDUCE(anorm,anorm_sum,1,MPI_REAL,
     .                   MPI_SUM,MPI_COMM_WORLD,ierr)

      end if

      if(n.gt.1.and.(anorm_sum.lt.vbmin)) then

c      jm = jmax
c      if ( rank == nworker-1 ) then
c      im = p_ie_o(rank) ! i=imax1
c      do 180 k=1,kmax2
c      do 180 j=1,jmax2
c      if(infw(1,j,k).eq.4) then
c      p_vv(2,j,k)    = p_vv(im,j,k)
c      p_vv(im+1,j,k) = p_vv(3,j,k)
c      end if
c  180 continue
c      endif
c
c      do 200 k=1,kmax2
c      do 200 i=p_is_g(rank),p_ie_g(rank) ! i=1,imax2
c      if(infs(i,1,k).eq.4) then
c      p_vv(i,1,k)    = p_vv(i,jm,k)
c      p_vv(i,jm+1,k) = p_vv(i,2,k)
c      end if
c  200 continue

      ! Update buffer at last
      call UPDATE_BUFFER_REAL(p_vv)

      return
      end if
  220 continue

      return 

      end



ccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_sorww
ccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  successive overrelaxation with the relaxation parameter omega.
!----------------------------------------------------------------------!      
      use moment_dim
      use common_mpi
      !----------------------------------------------------------------!      
      real(kind=8) :: stime,etime
      real :: resid, anorm,anorm_sum
      integer :: i,j,k,im,jm
!----------------------------------------------------------------------!      

      do 220 n=1,maxits


      p_dum(:,:,:) = 0.0

!     stime=MPI_WTIME()
      call UPDATE_BUFFER_REAL(p_ww)
!     etime=MPI_WTIME()

      anorm = 0. ; anorm_sum = 0.
      if(mod(n,2).eq.0) then
      do 120 k=2,kmax
      do 120 j=p_is_o(rank),p_ie_o(rank)
      do 120 i=2,imax1
  120 p_dum(i,j,k) = p_ww(i,j,k)
      end if
      do 140 k=2,kmax
      do 140 j=p_is_o(rank),p_ie_o(rank)
      do 140 i=2,imax1
      if(p_ijc(i,j,k).eq.0) go to 140
      if(p_odevn(i,j,k).eq.mod(n,2)) then
      resid = - p_s(i,j,k)
     .        -p_al(i,j,k)*p_ww(i  ,j  ,k-1)
     .        -p_as(i,j,k)*p_ww(i  ,j-1,k  )
     .        -p_aw(i,j,k)*p_ww(i-1,j  ,k  )
     .        -p_ah(i,j,k)*p_ww(i  ,j  ,k+1)
     .        -p_an(i,j,k)*p_ww(i  ,j+1,k  )
     .        -p_ae(i,j,k)*p_ww(i+1,j  ,k  )
     .       +p_apz(i,j,k)*p_ww(i  ,j  ,k  )
      p_ww(i,j,k) = p_ww(i,j,k)-omegag*resid/p_apz(i,j,k)
      end if
  140 continue

c  convergence test
      if(mod(n,2).eq.0) then
      do 160 k=2,kmax
      do 160 j=p_is_o(rank),p_ie_o(rank)
      do 160 i=2,imax1
      if(p_ijc(i,j,k).eq.0) go to 160
      if(abs(p_ww(i,j,k)).lt.cutw) go to 160
      anorm = anorm+abs((p_ww(i,j,k)-p_dum(i,j,k))/p_ww(i,j,k))
  160 continue
      anorm = anorm/float(itotal)

      call MPI_ALLREDUCE(anorm,anorm_sum,1,MPI_REAL,
     .                   MPI_SUM,MPI_COMM_WORLD,ierr)

      end if
      if(n.gt.1.and.(anorm_sum.lt.wbmin)) then
              
c      jm = jmax1
c      if ( rank == nworker-1 ) then
c      im = p_ie_o(rank) ! i=imax1
c      do 180 k=1,kmax2
c      do 180 j=1,jmax2
c      if(infw(1,j,k).eq.4) then
c      p_ww(2,j,k)    = p_ww(im,j,k)
c      p_ww(im+1,j,k) = p_ww(3,j,k)
c      end if
c  180 continue
c      endif
c
c      do 200 k=1,kmax2
c      do 200 i=p_is_g(rank),p_ie_g(rank) ! i=1,imax2
c      if(infs(i,1,k).eq.4) then
c      p_ww(i,1,k)    = p_ww(i,jm,k)
c      p_ww(i,jm+1,k) = p_ww(i,2,k)
c      end if
c  200 continue

      ! Update buffer at last
      call UPDATE_BUFFER_REAL(p_ww)

      return
      end if
  220 continue
      return 

      end


cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_sorpo
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  successive overrelaxation with the relaxation parameter omega.
!----------------------------------------------------------------------!      
      use moment_dim
      use common_mpi
      !----------------------------------------------------------------!      
      real :: resid, anorm,anorm_sum
      integer :: i,j,k,im,jm
!----------------------------------------------------------------------!      

      do 220 n=1,maxits

      p_dum(:,:,:) = 0.0

      call UPDATE_BUFFER_REAL(p_pdot)

      anorm = 0. ; anorm_sum = 0.
      if(mod(n,2).eq.0) then
      do 120 k=2,kmax1
      do 120 j=p_is_o(rank),p_ie_o(rank)
      do 120 i=2,imax1
  120 p_dum(i,j,k) = p_pdot(i,j,k)
      end if
      do 140 k=2,kmax1
      do 140 j=p_is_o(rank),p_ie_o(rank)
      do 140 i=2,imax1
      if(p_ijc(i,j,k).eq.0) go to 140
      if(p_odevn(i,j,k).eq.mod(n,2)) then
      resid = - p_s(i,j,k)
     .        -p_al(i,j,k)*p_pdot(i  ,j  ,k-1)
     .        -p_as(i,j,k)*p_pdot(i  ,j-1,k  )
     .        -p_aw(i,j,k)*p_pdot(i-1,j  ,k  )
     .        -p_ah(i,j,k)*p_pdot(i  ,j  ,k+1)
     .        -p_an(i,j,k)*p_pdot(i  ,j+1,k  )
     .        -p_ae(i,j,k)*p_pdot(i+1,j  ,k  )
     .       +p_app(i,j,k)*p_pdot(i  ,j  ,k  )
      p_pdot(i,j,k) = p_pdot(i,j,k)-omegag*resid/p_app(i,j,k)
      end if
  140 continue

c  convergence test
      if(mod(n,2).eq.0) then
      do 160 k=2,kmax1
      do 160 j=p_is_o(rank),p_ie_o(rank)
      do 160 i=2,imax1
      if(p_ijc(i,j,k).eq.0) go to 160
      if(abs(p_pdot(i,j,k)).lt.cutp) go to 160
      anorm = anorm+abs((p_pdot(i,j,k)-p_dum(i,j,k))/p_pdot(i,j,k))
  160 continue
      anorm = anorm/float(itotal)
      
      call MPI_ALLREDUCE(anorm,anorm_sum,1,MPI_REAL,
     .                   MPI_SUM,MPI_COMM_WORLD,ierr)

      end if
      if(n.gt.1.and.(anorm_sum.lt.pbmin)) then

c      jm = jmax1
c      if ( rank == nworker-1 ) then
c      im = p_ie_o(rank) ! i=imax1
c      do 180 k=1,kmax2
c      do 180 j=1,jmax2
c      if(infw(1,j,k).eq.4) then
c      p_pdot(2,j,k)    = p_pdot(im,j,k)
c      p_pdot(im+1,j,k) = p_pdot(3,j,k)
c      end if
c  180 continue
c      endif
c
c      do 200 k=1,kmax2
c      do 200 i=p_is_g(rank),p_ie_g(rank) ! i=1,imax2
c      if(infs(i,1,k).eq.4) then
c      p_pdot(i,1,k)    = p_pdot(i,jm,k)
c      p_pdot(i,jm+1,k) = p_pdot(i,2,k)
c      end if
c  200 continue

      ! Update buffer at last
      call UPDATE_BUFFER_REAL(p_pdot)

      return
      end if
  220 continue
      return 

      end


cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_sorco
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  successive overrelaxation with the relaxation parameter omega.
!----------------------------------------------------------------------!      
      use moment_dim
      use common_mpi

      real(kind=8) :: anorm_sum
      real(kind=8) :: anum,aden,anum_s,aden_s
      integer :: i,j,k
!----------------------------------------------------------------------!

      do 220 n=1,maxits

      call UPDATE_BUFFER_REAL(p_co)

      anorm_sum = 0.d0
      anum   = 0.d0 ; aden   = 0.d0
      anum_s = 0.d0 ; aden_s = 0.d0

      if(mod(n,2).eq.1) then
      do 120 k=2,kmax1
      do 120 j=p_is_o(rank),p_ie_o(rank)
      do 120 i=2,imax1 ! 2~imax1
  120 p_dum(i,j,k) = p_co(i,j,k)
      end if

      do 140 k=2,kmax1
      do 140 j=p_is_o(rank),p_ie_o(rank)
      do 140 i=2,imax1 ! 2~imax1
      if(p_ijc(i,j,k).eq.0) go to 140
      if(p_odevn(i,j,k).eq.mod(n,2)) then
      resid = - p_s(i,j,k)
     .        -p_al(i,j,k)*p_co(i  ,j  ,k-1)
     .        -p_as(i,j,k)*p_co(i  ,j-1,k  )
     .        -p_aw(i,j,k)*p_co(i-1,j  ,k  )
     .        -p_ah(i,j,k)*p_co(i  ,j  ,k+1)
     .        -p_an(i,j,k)*p_co(i  ,j+1,k  )
     .        -p_ae(i,j,k)*p_co(i+1,j  ,k  )
     .      +p_apco(i,j,k)*p_co(i  ,j  ,k  )
      p_co(i,j,k) = p_co(i,j,k)-omegag*resid/p_apco(i,j,k)
      end if
  140 continue

c  convergence test
      if(mod(n,2).eq.0) then

      do 160 k=2,kmax1
      do 160 j=p_is_o(rank),p_ie_o(rank)
      do 160 i=2,imax1 ! 2~imax !! imax !!!!
      if(p_ijc(i,j,k).eq.0) go to 160
      anum = anum+dble(abs(p_co(i,j,k)-p_dum(i,j,k)))
      aden = aden+dble(abs(p_co(i,j,k)))
  160 continue
      call MPI_ALLREDUCE(anum,anum_s,1,
     .                   MPI_DOUBLE_PRECISION,
     .                   MPI_SUM,MPI_COMM_WORLD,ierr)
      call MPI_ALLREDUCE(aden,aden_s,1,
     .                   MPI_DOUBLE_PRECISION,
     .                   MPI_SUM,MPI_COMM_WORLD,ierr)
      anorm_sum = anum_s/max(aden_s,1.d-30)

      end if

      if(n.gt.1.and.mod(n,2).eq.0.and.
     .   anorm_sum.lt.cbmin) then
      call UPDATE_BUFFER_REAL(p_co)

      return
      end if


  220 continue

      call UPDATE_BUFFER_REAL(p_co)
      return

      end


cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_coeft
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  calculate the coefficients of the finite difference
c  equation for the temperature equation
!----------------------------------------------------------------------!      
      use moment_dim
      use common_mpi
!----------------------------------------------------------------------!      
      
      p_vit(:,:,:) = p_vis(:,:,:)/Prt
      p_al(:,:,:) = 0.
      p_ah(:,:,:) = 0.
      p_as(:,:,:) = 0.
      p_an(:,:,:) = 0.
      p_aw(:,:,:) = 0.
      p_ae(:,:,:) = 0.

      do 200 k=2,kmax1
      do 200 j=p_is_o(rank),p_ie_o(rank)
      do 200 i=2,imax1
      if(p_ijc(i,j,k).eq.0) go to 200

      if(p_ijc(i,j,k-1).eq.0) then
      dlzm = 0.5*dz(k)
      else
      dlzm = delz(k-1)
      end if

      if(p_ijc(i,j,k+1).eq.0) then
      dlzp = 0.5*dz(k)
      else
      dlzp = delz(k)
      end if

      if(p_ijc(i-1,j,k).eq.0) then
      dlxm = 0.5*dx(i)
      else
      dlxm = delx(i-1)
      end if

      if(p_ijc(i+1,j,k).eq.0) then
      dlxp = 0.5*dx(i)
      else
      dlxp = delx(i)
      end if

      if(p_ijc(i,j-1,k).eq.0) then
      dlym = 0.5*p_dy(j)
      else
      dlym = p_dely(j-1)
      end if

      if(p_ijc(i,j+1,k).eq.0) then
      dlyp = 0.5*p_dy(j)
      else
      dlyp = p_dely(j)
      end if

      dl  = (dz(k)*p_vit(i,j,k-1)+dz(k-1)*p_vit(i,j,k))
     .      /((dz(k-1)+dz(k))*dlzm)
      den = (p_dena(i,j,k-1)+p_dena(i,j,k-1)
     .      +p_dena(i,j,k  )+p_dena(i,j,k  ))/4.
      fz  = den*p_ww(i,j,k-1)
      p_al(i,j,k) = dx(i)*p_dy(j)
     .            *(dl*amax1(0.,(1.-0.1*abs(fz)/dl)**5)+amax1(fz,0.))
     .            *p_afsc(i,j,k)

      ds  = (p_dy(j)*p_vit(i,j-1,k)+p_dy(j-1)*p_vit(i,j,k))
     .      /((p_dy(j-1)+p_dy(j))*dlym)
      den = (p_dena(i,j-1,k)+p_dena(i,j-1,k)
     .      +p_dena(i,j  ,k)+p_dena(i,j  ,k))/4.
      fy  = den*p_vv(i,j-1,k)
      p_as(i,j,k) = dx(i)*dz(k)
     .            *(ds*amax1(0.,(1.-0.1*abs(fy)/ds)**5)+amax1(fy,0.))
     .            *p_afsb(i,j-1,k)

      dw  = (dx(i)*p_vit(i-1,j,k)+dx(i-1)*p_vit(i,j,k))
     .      /((dx(i-1)+dx(i))*dlxm)
      den = (p_dena(i-1,j,k)+p_dena(i-1,j,k)
     .      +p_dena(i  ,j,k)+p_dena(i  ,j,k))/4.
      fx  = den*p_uu(i-1,j,k)
      p_aw(i,j,k) = p_dy(j)*dz(k)
     .            *(dw*amax1(0.,(1.-0.1*abs(fx)/dw)**5)+amax1(fx,0.))
     .            *p_afsa(i,j,k)
 
      de  = (dx(i+1)*p_vit(i,j,k)+dx(i)*p_vit(i+1,j,k))
     .      /((dx(i)+dx(i+1))*dlxp)
      den = (p_dena(i  ,j,k)+p_dena(i  ,j,k)
     .      +p_dena(i+1,j,k)+p_dena(i+1,j,k))/4.
      fx  = den*p_uu(i,j,k)
      p_ae(i,j,k) = p_dy(j)*dz(k)
     .            *(de*amax1(0.,(1.-0.1*abs(fx)/de)**5)+amax1(0.,-fx))
     .            *p_afsa(i+1,j,k)
  
      dn  = (p_dy(j+1)*p_vit(i,j,k)+p_dy(j)*p_vit(i,j+1,k))
     .      /((p_dy(j)+p_dy(j+1))*dlyp)
      den = (p_dena(i,j  ,k)+p_dena(i,j  ,k)
     .      +p_dena(i,j+1,k)+p_dena(i,j+1,k))/4.
      fy  = den*p_vv(i,j,k)
      p_an(i,j,k) = dx(i)*dz(k)
     .            *(dn*amax1(0.,(1.-0.1*abs(fy)/dn)**5)+amax1(0.,-fy))
     .            *p_afsb(i,j,k)

      dh  = (dz(k+1)*p_vit(i,j,k)+dz(k)*p_vit(i,j,k+1))
     .      /((dz(k)+dz(k+1))*dlzp)
      den = (p_dena(i,j,k  )+p_dena(i,j,k  )
     .      +p_dena(i,j,k+1)+p_dena(i,j,k+1))/4.
      fz  = den*p_ww(i,j,k)
      p_ah(i,j,k) = dx(i)*p_dy(j)*(dh*amax1(0.,(1.-0.1*abs(fz)/dh)**5)+
     .  amax1(0.,-fz)) *p_afsc(i,j,k+1)

      p_aptt(i,j,k) = p_denao(i,j,k)*dx(i)*p_dy(j)*dz(k)
     .             *p_afsv(i,j,k)/delt+
!     .             /delt+
     .                  p_ae(i,j,k)+p_aw(i,j,k)+p_an(i,j,k)+
     .                  p_as(i,j,k)+p_ah(i,j,k)+p_al(i,j,k)
 
      p_s(i,j,k) = p_denao(i,j,k)*dx(i)*p_dy(j)*dz(k)
     .          *p_afsv(i,j,k)*p_tto(i,j,k)/delt 
!     .          *p_tto(i,j,k)/delt 

      if(p_ijc(i,j,k-1).eq.0 .and. p_ijc(i,j,k).ne.0) then
      if(p_fire_2d(i,j,1).gt.0.) then !HJ
      p_s(i,j,k) = p_s(i,j,k) + p_fire_2d(i,j,1)*dx(i)*p_dy(j)/cp ! JH fire
!      print*, i,j,p_fire_2d(i,j,1)*dx(i)*p_dy(j)/cp,p_fire_2d(i,j,1)
      end if
      end if

  200 continue

c  implement boundary conditions
c  at the lower boundary (dirichlet condition)
      do 220 j=p_is_o(rank),p_ie_o(rank)
      do 220 i=2,imax1

      if(p_ijc(i,j,2).ne.0) then

      if(iloca6.eq.1) then

      yplus = 0.5*dz(2)*cu**0.25*p_EE(i,j,2)**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = p_dena(i,j,2)*cu**0.25*p_EE(i,j,2)**0.5
      uplus = alog(9.793*yplus)/tkapa
      pp = 9.24*((Pr/Prt)**0.75-1.)*(1.+0.28/exp(0.007*Pr/Prt))
      tplus = Prt*(uplus + pp)
      p_spT(i,j,2) = -deno1/tplus*dx(i)*p_dy(j)
      p_swT(i,j,2) = deno1/tplus*p_tt(i,j,1)*dx(i)*p_dy(j)
      else
      p_spT(i,j,2) = -vism/Pr/(0.5*dz(2))*dx(i)*p_dy(j)
      p_swT(i,j,2) =  vism/Pr/(0.5*dz(2))*p_tt(i,j,1)*dx(i)*p_dy(j)
      endif

      p_aptt(i,j,2) = p_aptt(i,j,2) - p_spT(i,j,2)
         p_s(i,j,2) = p_s(i,j,2)+p_tt(i,j,1)*p_al(i,j,2) + p_swT(i,j,2)
        p_al(i,j,2) = 0.
 

      else

       p_s(i,j,2)  = p_s(i,j,2)+p_tt(i,j,1)*p_al(i,j,2)
      p_al(i,j,2) = 0.


      end if

      end if

  220 continue

c  at the top of the model (shear-free condition)
      do 240 j=p_is_o(rank),p_ie_o(rank)
      do 240 i=2,imax1
      p_aptt(i,j,kmax1) = p_aptt(i,j,kmax1)-p_ah(i,j,kmax1)
        p_ah(i,j,kmax1)   = 0.
  240 continue

c  at the top of the buildings (dirichlet condition)
      do 260 k=3,kmax1
      do 260 j=p_is_o(rank),p_ie_o(rank)
      do 260 i=2,imax1

      if((p_ijc(i,j,k).eq.1).and.(p_ijc(i,j,k-1).eq.0)) then

      if(iloca5.eq.1) then

      yplus = 0.5*dz(k)*cu**0.25*p_EE(i,j,k)**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = p_dena(i,j,k)*cu**0.25*p_EE(i,j,k)**0.5
      uplus = alog(9.793*yplus)/tkapa
      pp = 9.24*((Pr/Prt)**0.75-1.)*(1.+0.28/exp(0.007*Pr/Prt))
      tplus = Prt*(uplus + pp)
      p_spT(i,j,k) = -deno1/tplus*dx(i)*p_dy(j)*(1.-p_afsc(i,j,k))
      p_swT(i,j,k) =  deno1/tplus*p_tt(i,j,k-1)*dx(i)*p_dy(j)
     .               *(1. - p_afsc(i,j,k))
      else
      p_spT(i,j,k) = -vism/Pr/(0.5*dz(k))*dx(i)*p_dy(j)
     .   *(1.-p_afsc(i,j,k))
      p_swT(i,j,k) =  vism/Pr/(0.5*dz(k))*p_tt(i,j,k-1)*dx(i)*p_dy(j)
     .               * (1. - p_afsc(i,j,k))
      endif

      p_aptt(i,j,k) = p_aptt(i,j,k) - p_spT(i,j,k)
         p_s(i,j,k) = p_s(i,j,k)+p_tt(i,j,k-1)*p_al(i,j,k)+p_swT(i,j,k)
      p_al(i,j,k) = 0.
      else

       p_s(i,j,k) = p_s(i,j,k)+p_tt(i,j,k-1)*p_al(i,j,k)
      p_al(i,j,k) = 0.
      end if

      endif

      if((p_ijc(i,j,k).eq.1).and.(p_ijc(i,j,k+1).eq.0)) then

      if(iloca7.eq.1) then

      yplus = 0.5*dz(k)*cu**0.25*p_EE(i,j,k)**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = p_dena(i,j,k)*cu**0.25*p_EE(i,j,k)**0.5
      uplus = alog(9.793*yplus)/tkapa
      pp = 9.24*((Pr/Prt)**0.75-1.)*(1.+0.28/exp(0.007*Pr/Prt))
      tplus = Prt*(uplus + pp)
      p_spT(i,j,k) = -deno1/tplus*dx(i)*p_dy(j)*(1.-p_afsc(i,j,k+1))
      p_swT(i,j,k) =  deno1/tplus*p_tt(i,j,k+1)*dx(i)*p_dy(j)
     .               *(1.-p_afsc(i,j,k+1)) 
      else
      p_spT(i,j,k)=-vism/Pr/(0.5*dz(k))*dx(i)*p_dy(j)
     .   *(1.-p_afsc(i,j,k+1))
      p_swT(i,j,k) =  vism/Pr/(0.5*dz(k))*p_tt(i,j,k+1)*dx(i)*p_dy(j)
     .              *(1.-p_afsc(i,j,k+1))
      endif

      p_aptt(i,j,k) = p_aptt(i,j,k) - p_spT(i,j,k)
         p_s(i,j,k) = p_s(i,j,k)+p_tt(i,j,k+1)*p_ah(i,j,k)+p_swT(i,j,k)
        p_ah(i,j,k) = 0.
      else

         p_s(i,j,k) = p_s(i,j,k)+p_tt(i,j,k+1)*p_ah(i,j,k)
        p_ah(i,j,k) = 0.
      end if

      endif

      if(p_ijc(i,j,k).eq.2) then
      if((iloca5.eq.1).or.(iloca7.eq.1)) then

      awall = 0.
      twall = 0.
      if(p_ijc(i,j,k-1).eq.0) then
      awall = awall + (1.-p_afsc(i,j,k))
      twall = twall + p_tt(i,j,k-1)*(1.-p_afsc(i,j,k))
      endif
      if(p_ijc(i,j,k+1).eq.0) then
      awall = awall + (1.-p_afsc(i,j,k+1))
      twall = twall + p_tt(i,j,k+1)*(1.-p_afsc(i,j,k+1))
      endif

      acut = abs(p_afsc(i,j,k+1)-p_afsc(i,j,k))

      if((awall.gt.1.e-12).and.(acut.gt.1.e-12)) then
      twall = twall/awall

      yplus = 0.5*dz(k)*cu**0.25*p_EE(i,j,k)**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = p_dena(i,j,k)*cu**0.25*p_EE(i,j,k)**0.5
      uplus = alog(9.793*yplus)/tkapa
      pp = 9.24*((Pr/Prt)**0.75-1.)*(1.+0.28/exp(0.007*Pr/Prt))
      tplus = Prt*(uplus + pp)
      p_spT(i,j,k) = -deno1/tplus*dx(i)*p_dy(j)*acut
      p_swT(i,j,k) = deno1/tplus*twall*dx(i)*p_dy(j)*acut
      else
      p_spT(i,j,k) = -vism/Pr/(0.5*dz(k))*dx(i)*p_dy(j)*acut
      p_swT(i,j,k) = vism/Pr/(0.5*dz(k))*twall*dx(i)*p_dy(j)*acut
      endif

      p_aptt(i,j,k) = p_aptt(i,j,k) - p_spT(i,j,k)
      p_s(i,j,k) = p_s(i,j,k) + p_swT(i,j,k)

      endif
      end if
      endif

  260 continue

c  at the building walls (dirichlet condition)
      do 280 k=2,kmax1
      do 280 j=p_is_o(rank),p_ie_o(rank)
      do 280 i=2,imax1

      if(p_ijc(i,j,k).eq.1) then

      if(p_ijc(i-1,j,k).eq.0) then

      if(iloca1.eq.1) then

      yplus = 0.5*dx(i)*cu**0.25*p_EE(i,j,k)**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = p_dena(i,j,k)*cu**0.25*p_EE(i,j,k)**0.5
      uplus = alog(9.793*yplus)/tkapa
      pp = 9.24*((Pr/Prt)**0.75-1.)*(1.+0.28/exp(0.007*Pr/Prt))
      tplus = Prt*(uplus + pp)
      p_spT(i,j,k) = -deno1/tplus*p_dy(j)*dz(k)*(1.-p_afca(i,j,k))
      p_swT(i,j,k) =  deno1/tplus*p_tt(i-1,j,k)*p_dy(j)*dz(k)
     . *(1.-p_afca(i,j,k))
      else
      p_spT(i,j,k)=-vism/Pr/(0.5*dx(i))*p_dy(j)*dz(k)*(1.-p_afca(i,j,k))
      p_swT(i,j,k) =  vism/Pr/(0.5*dx(i))*p_tt(i-1,j,k)*p_dy(j)*dz(k)
     . *(1.-p_afca(i,j,k))
      endif

      p_aptt(i,j,k) = p_aptt(i,j,k) - p_spT(i,j,k)
      p_s(i,j,k) = p_s(i,j,k) + p_tt(i-1,j,k)*p_aw(i,j,k) + p_swT(i,j,k)
        p_aw(i,j,k) = 0.
      else

      p_s(i,j,k)  = p_s(i,j,k)+p_tt(i-1,j,k)*p_aw(i,j,k)
        p_aw(i,j,k) = 0.
      end if

      endif

      if(p_ijc(i+1,j,k).eq.0) then

      if(iloca2.eq.1) then

      yplus = 0.5*dx(i)*cu**0.25*p_EE(i,j,k)**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = p_dena(i,j,k)*cu**0.25*p_EE(i,j,k)**0.5
      uplus = alog(9.793*yplus)/tkapa
      pp = 9.24*((Pr/Prt)**0.75-1.)*(1.+0.28/exp(0.007*Pr/Prt))
      tplus = Prt*(uplus + pp)
      p_spT(i,j,k) = -deno1/tplus*p_dy(j)*dz(k)*(1.-p_afca(i+1,j,k))
      p_swT(i,j,k) =  deno1/tplus*p_tt(i+1,j,k)*p_dy(j)*dz(k)
     . *(1.-p_afca(i+1,j,k))
      else
      p_spT(i,j,k)=-vism/Pr/(0.5*dx(i))*p_dy(j)*dz(k)
     . *(1.-p_afca(i+1,j,k))
      p_swT(i,j,k) =  vism/Pr/(0.5*dx(i))*p_tt(i+1,j,k)*p_dy(j)*dz(k)
     . *(1.-p_afca(i+1,j,k))
      endif

      p_aptt(i,j,k) = p_aptt(i,j,k) - p_spT(i,j,k)
      p_s(i,j,k) = p_s(i,j,k) + p_tt(i+1,j,k)*p_ae(i,j,k) + p_swT(i,j,k)
        p_ae(i,j,k) = 0.
      else

      p_s(i,j,k)  = p_s(i,j,k)+p_tt(i+1,j,k)*p_ae(i,j,k)
        p_ae(i,j,k) = 0.
      end if

      endif

      if(p_ijc(i,j-1,k).eq.0) then

      if(iloca3.eq.1) then

      yplus = 0.5*p_dy(j)*cu**0.25*p_EE(i,j,k)**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = p_dena(i,j,k)*cu**0.25*p_EE(i,j,k)**0.5
      uplus = alog(9.793*yplus)/tkapa
      pp = 9.24*((Pr/Prt)**0.75-1.)*(1.+0.28/exp(0.007*Pr/Prt))
      tplus = Prt*(uplus + pp)
      p_spT(i,j,k) = -deno1/tplus*dx(i)*dz(k)*(1.-p_afcb(i,j-1,k))
      p_swT(i,j,k) =  deno1/tplus*p_tt(i,j-1,k)*dx(i)*dz(k)
     .  *(1.-p_afcb(i,j-1,k))
      else
      p_spT(i,j,k) = -vism/Pr/(0.5*p_dy(j))*dx(i)*dz(k)
     . *(1.-p_afcb(i,j-1,k))
      p_swT(i,j,k) =  vism/Pr/(0.5*p_dy(j))*p_tt(i,j-1,k)*dx(i)*dz(k)
     . *(1.-p_afcb(i,j-1,k))
      endif

      p_aptt(i,j,k) = p_aptt(i,j,k) - p_spT(i,j,k)
      p_s(i,j,k) = p_s(i,j,k) + p_tt(i,j-1,k)*p_as(i,j,k) + p_swT(i,j,k)
        p_as(i,j,k) = 0.
      else

      p_s(i,j,k)  = p_s(i,j,k)+p_tt(i,j-1,k)*p_as(i,j,k)
        p_as(i,j,k) = 0.
      end if

      endif

      if(p_ijc(i,j+1,k).eq.0) then

      if(iloca4.eq.1) then

      yplus = 0.5*p_dy(j)*cu**0.25*p_EE(i,j,k)**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = p_dena(i,j,k)*cu**0.25*p_EE(i,j,k)**0.5
      uplus = alog(9.793*yplus)/tkapa
      pp = 9.24*((Pr/Prt)**0.75-1.)*(1.+0.28/exp(0.007*Pr/Prt))
      tplus = Prt*(uplus + pp)
      p_spT(i,j,k) = -deno1/tplus*dx(i)*dz(k)*(1.-p_afcb(i,j,k))
      p_swT(i,j,k) =  deno1/tplus*p_tt(i,j+1,k)*dx(i)*dz(k)
     . *(1.-p_afcb(i,j,k))
      else
      p_spT(i,j,k) = -vism/Pr/(0.5*p_dy(j))*dx(i)*dz(k)
     .   *(1.-p_afcb(i,j,k))
      p_swT(i,j,k) =  vism/Pr/(0.5*p_dy(j))*p_tt(i,j+1,k)*dx(i)*dz(k)
     . *(1.-p_afcb(i,j,k))
      endif

      p_aptt(i,j,k) = p_aptt(i,j,k) - p_spT(i,j,k)
      p_s(i,j,k) = p_s(i,j,k) + p_tt(i,j+1,k)*p_an(i,j,k) + p_swT(i,j,k)
        p_an(i,j,k) = 0.
      else

      p_s(i,j,k)  = p_s(i,j,k)+p_tt(i,j+1,k)*p_an(i,j,k)
        p_an(i,j,k) = 0.
      end if

      endif

      end if

      if(p_ijc(i,j,k).eq.2) then

      if((iloca1.eq.1).or.(iloca2.eq.1)) then

      awall = 0.
      twall = 0.
      if(p_ijc(i-1,j,k).eq.0) then
      awall = awall + (1.-p_afca(i,j,k))
      twall = twall + p_tt(i-1,j,k)*(1.-p_afca(i,j,k))
      endif
      if(p_ijc(i+1,j,k).eq.0) then
      awall = awall + (1.-p_afca(i+1,j,k))
      twall = twall + p_tt(i+1,j,k)*(1.-p_afca(i+1,j,k))
      endif

      acut = abs(p_afca(i+1,j,k)-p_afca(i,j,k))

      if((awall.gt.1.e-12).and.(acut.gt.1.e-12)) then
      twall = twall/awall

      yplus = 0.5*dx(i)*cu**0.25*p_EE(i,j,k)**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = p_dena(i,j,k)*cu**0.25*p_EE(i,j,k)**0.5
      uplus = alog(9.793*yplus)/tkapa
      pp = 9.24*((Pr/Prt)**0.75-1.)*(1.+0.28/exp(0.007*Pr/Prt))
      tplus = Prt*(uplus + pp)
      p_spT(i,j,k) = -deno1/tplus*p_dy(j)*dz(k)*acut
      p_swT(i,j,k) = deno1/tplus*twall*p_dy(j)*dz(k)*acut
      else
      p_spT(i,j,k) = -vism/Pr/(0.5*dx(i))*p_dy(j)*dz(k)*acut
      p_swT(i,j,k) = vism/Pr/(0.5*dx(i))*twall*p_dy(j)*dz(k)*acut
      endif

      p_aptt(i,j,k) = p_aptt(i,j,k) - p_spT(i,j,k)
      p_s(i,j,k) = p_s(i,j,k) + p_swT(i,j,k)
      endif
      end if

      if((iloca3.eq.1).or.(iloca4.eq.1)) then

      awall = 0.
      twall = 0.
      if(p_ijc(i,j-1,k).eq.0) then
      awall = awall + (1.-p_afcb(i,j-1,k))
      twall = twall + p_tt(i,j-1,k)*(1.-p_afcb(i,j-1,k))
      endif
      if(p_ijc(i,j+1,k).eq.0) then
      awall = awall + (1.-p_afcb(i,j,k))
      twall = twall + p_tt(i,j+1,k)*(1.-p_afcb(i,j,k))
      endif

      acut = abs(p_afcb(i,j,k)-p_afcb(i,j-1,k))

      if((awall.gt.1.e-12).and.(acut.gt.1.e-12)) then
      twall = twall/awall

      yplus = 0.5*p_dy(j)*cu**0.25*p_EE(i,j,k)**0.5/visl

      if(yplus.gt.ynd) then
      deno1 = p_dena(i,j,k)*cu**0.25*p_EE(i,j,k)**0.5
      uplus = alog(9.793*yplus)/tkapa
      pp = 9.24*((Pr/Prt)**0.75-1.)*(1.+0.28/exp(0.007*Pr/Prt))
      tplus = Prt*(uplus + pp)
      p_spT(i,j,k) = -deno1/tplus*dx(i)*dz(k)*acut
      p_swT(i,j,k) = deno1/tplus*twall*dx(i)*dz(k)*acut
      else
      p_spT(i,j,k) = -vism/Pr/(0.5*p_dy(j))*dx(i)*dz(k)*acut
      p_swT(i,j,k) = vism/Pr/(0.5*p_dy(j))*twall*dx(i)*dz(k)*acut
      endif

      p_aptt(i,j,k) = p_aptt(i,j,k) - p_spT(i,j,k)
      p_s(i,j,k) = p_s(i,j,k) + p_swT(i,j,k)
      endif
      end if

      endif

  280 continue
c  at the horizontal boundaries

c  x = 0
c  shear-free or outflow conditions?


c      if((infw.eq.0).or.(infw.eq.2)) then
      do 320 k=2,kmax1
      do 320 j=p_is_o(rank),p_ie_o(rank)
      if((infw(1,j,k).eq.0).or.(infw(1,j,k).eq.2)) then
      if(p_ijc(2,j,k).ne.0) then
      p_aptt(2,j,k) = p_aptt(2,j,k)-p_aw(2,j,k)
      p_aw(2,j,k)   = 0.
      end if
      end if
  320 continue
c  inflow conditions?
c      if(infw.eq.1) then
      do 340 k=2,kmax1
      do 340 j=p_is_o(rank),p_ie_o(rank)
      if(infw(1,j,k).eq.1) then
      if(p_ijc(2,j,k).ne.0) then
!      p_tt(iss,j,k) = tair+273.15
      p_tt(1,j,k) = p_tair(1,j,k)+273.15
          !iss!
      p_s(2,j,k)  = p_s(2,j,k)+p_tt(1,j,k)*p_aw(2,j,k)
                                     !iss!
      p_aw(2,j,k) = 0.
      end if
      end if
  340 continue



c  x = xmax
c  shear-free or outflow conditions?
     

c      if((infe.eq.0).or.(infe.eq.2)) then
      do 360 k=2,kmax1
      do 360 j=p_is_o(rank),p_ie_o(rank)
      if((infe(imax2,j,k).eq.0).or.(infe(imax2,j,k).eq.2)) then
      if(p_ijc(imax1,j,k).ne.0) then
      p_aptt(imax1,j,k) = p_aptt(imax1,j,k)-p_ae(imax1,j,k)
      p_ae(imax1,j,k)   = 0.
      end if
      end if
  360 continue
c  inflow conditions?
c      if(infe.eq.1) then
      do 380 k=2,kmax1
      do 380 j=p_is_o(rank),p_ie_o(rank)
      if(infe(imax2,j,k).eq.1) then
      if(p_ijc(imax1,j,k).ne.0) then
!      p_tt(iee,j,k) = tair+273.15
      p_tt(imax2,j,k) = p_tair(imax2,j,k)+273.15
          !iee!
      p_s(imax1,j,k)  = p_s(imax1,j,k)+p_tt(imax2,j,k)*p_ae(imax1,j,k)
                                     !iee!
      p_ae(imax1,j,k) = 0.
      end if
      end if
  380 continue



c  y = 0
      if ( rank == 0 ) then ! WORKER 1 only for x = 0 ##################
      is   = p_is_o(rank) ! = 2
      iss  = p_is_g(rank) ! = 1
c  shear-free or outflow conditions?
c      if((infs.eq.0).or.(infs.eq.2)) then
      do 400 k=2,kmax1
      do 400 i=2,imax1 ! 2~imax1
      if((infs(i,iss,k).eq.0).or.(infs(i,iss,k).eq.2)) then
      if(p_ijc(i,is,k).ne.0) then
      p_aptt(i,is,k) = p_aptt(i,is,k)-p_as(i,is,k)
      p_as(i,is,k)   = 0.
      end if
      end if
  400 continue
c  inflow conditions?
c      if(infs.eq.1) then
      do 420 k=2,kmax1
      do 420 i=2,imax1 ! 2~imax1
      if(infs(i,iss,k).eq.1) then
      if(p_ijc(i,is,k).ne.0) then
!      p_tt(i,1,k) = tair+273.15
      p_tt(i,iss,k) = p_tair(i,iss,k)+273.15
       p_s(i,is,k) = p_s(i,is,k)+p_tt(i,iss,k)*p_as(i,is,k)
      p_as(i,is,k) = 0.
      end if
      end if
  420 continue
      end if

c  y = ymax
      if ( rank == nworker-1 ) then ! WORKER nworker only for x = xmax ###
      ie   = p_ie_o(rank)  ! = imax1
      iee  = p_imax1(rank) ! = imax2
c      if((infn.eq.0).or.(infn.eq.2)) then
      do 440 k=2,kmax1
      do 440 i=2,imax1 ! 2~imax1
      if((infn(i,iee,k).eq.0).or.(infn(i,iee,k).eq.2)) then
      if(p_ijc(i,ie,k).ne.0) then
      p_aptt(i,ie,k) = p_aptt(i,ie,k)-p_an(i,ie,k)
      p_an(i,ie,k)   = 0.
      end if
      end if
  440 continue
c  inflow conditions?
c      if(infn.eq.1) then
      do 460 k=2,kmax1
      do 460 i=2,imax1 ! 2~imax1
      if(infn(i,iee,k).eq.1) then
      if(p_ijc(i,ie,k).ne.0) then
!      p_tt(i,jmax2,k) = tair+273.15
      p_tt(i,iee,k) = p_tair(i,iee,k)+273.15
      p_s(i,ie,k)  = p_s(i,ie,k)+p_tt(i,iee,k)*p_an(i,ie,k)
      p_an(i,ie,k) = 0.
      end if
      end if
  460 continue
      end if

      return
      end


cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      subroutine p_sortt
cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
c  successive overrelaxation with the relaxation parameter omega.
!----------------------------------------------------------------------!      
      use moment_dim
      use common_mpi
      !----------------------------------------------------------------!      
      real :: resid, anorm,anorm_sum
      integer :: i,j,k,im,jm
!----------------------------------------------------------------------!      

      do 220 n=1,maxits

      p_dum(:,:,:) = 0.0

      call UPDATE_BUFFER_REAL(p_tt)

      anorm = 0. ; anorm_sum = 0.
      if(mod(n,2).eq.0) then
      do 120 k=2,kmax1
      do 120 j=p_is_o(rank),p_ie_o(rank)
      do 120 i=2,imax1 ! 2~imax1
  120 p_dum(i,j,k) = p_tt(i,j,k)
      end if

      do 140 k=2,kmax1
      do 140 j=p_is_o(rank),p_ie_o(rank)
      do 140 i=2,imax1 ! 2~imax1
      if(p_ijc(i,j,k).eq.0) go to 140
      if(p_odevn(i,j,k).eq.mod(n,2)) then
      resid = - p_s(i,j,k)
     .        -p_al(i,j,k)*p_tt(i  ,j  ,k-1)
     .        -p_as(i,j,k)*p_tt(i  ,j-1,k  )
     .        -p_aw(i,j,k)*p_tt(i-1,j  ,k  )
     .        -p_ah(i,j,k)*p_tt(i  ,j  ,k+1)
     .        -p_an(i,j,k)*p_tt(i  ,j+1,k  )
     .        -p_ae(i,j,k)*p_tt(i+1,j  ,k  )
     .      +p_aptt(i,j,k)*p_tt(i  ,j  ,k  )
      p_tt(i,j,k) = p_tt(i,j,k)-omegag*resid/p_aptt(i,j,k)
      end if
  140 continue





c  convergence test
      if(mod(n,2).eq.0) then
      do 160 k=2,kmax1
                                          !          p_ie_u
      do 160 j=p_is_o(rank),p_ie_o(rank)
      do 160 i=2,imax ! 2~imax !! imax !!!!
      if(p_ijc(i,j,k).eq.0) go to 160
      if(abs(p_tt(i,j,k)).lt.cutt) go to 160
      anorm = anorm+abs((p_tt(i,j,k)-p_dum(i,j,k))/p_tt(i,j,k))
  160 continue
      anorm = anorm/float(itotal)

      call MPI_ALLREDUCE(anorm,anorm_sum,1,MPI_REAL,
     .                   MPI_SUM,MPI_COMM_WORLD,ierr)

      end if
      if(n.gt.1.and.(anorm_sum.lt.tbmin)) then

c      jm = jmax1
c      if ( rank == nworker-1 ) then
c      im = p_ie_o(rank) ! i=imax1
c      do 180 k=1,kmax2
c      do 180 j=1,jmax2
c      if(infw(1,j,k).eq.4) then
c      p_tt(2,j,k)    = p_tt(im,j,k)
c      p_tt(im+1,j,k) = p_tt(3,j,k)
c      end if
c  180 continue
c      endif
c
c      do 200 k=1,kmax2
c      do 200 i=p_is_g(rank),p_ie_g(rank) ! i=1,imax2
c      if(infs(i,1,k).eq.4) then
c      p_tt(i,1,k)    = p_tt(i,jm,k)
c      p_tt(i,jm+1,k) = p_tt(i,2,k)
c      end if
c  200 continue

      ! Update buffer at last
      call UPDATE_BUFFER_REAL(p_tt)

      return
      end if
  220 continue


!       p_tt(i,j,k) = 1200. + 273.15
!  141 continue




      return 

      end
