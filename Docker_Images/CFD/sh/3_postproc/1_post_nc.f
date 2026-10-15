      PROGRAM POST_NC_UVWC
      use netcdf
      implicit none

      include '../data/Domain/postproc_domain.inc'
      integer,parameter :: imax1 = imax+1,  jmax1 = jmax+1
      integer,parameter :: kmax1 = kmax+1
      integer,parameter :: imax2 = imax1+1, jmax2 = jmax1+1
      integer,parameter :: kmax2 = kmax1+1

      character(len=*),parameter :: topfile =
     &'../0_TOPO/top/cut_auto.top'
      character(len=*),parameter :: domaininfofile =
     &'../data/Domain/output_model_info.txt'
      character(len=*),parameter :: indir  = '../2_moment/results'
      character(len=*),parameter :: outdir = './results'

      integer,parameter :: deflate    = 1
      logical,parameter :: mask_solid = .true.

      real,parameter :: FILLV = NF90_FILL_REAL

      real,allocatable :: uu(:,:,:), vv(:,:,:), ww(:,:,:)
      real,allocatable :: tt(:,:,:), ee(:,:,:), co(:,:,:)
      integer,allocatable :: ijs(:,:,:)

      real,allocatable :: u(:,:,:), v(:,:,:), w(:,:,:), c(:,:,:)

      real,allocatable :: sur_u(:,:), sur_v(:,:), sur_w(:,:)
      real,allocatable :: sur_c(:,:)
      logical,allocatable :: sur_found(:,:)

      real,allocatable :: dx(:), dy(:), dz(:)
      real,allocatable :: px(:), py(:), pz(:)
      real,allocatable :: x(:), y(:), z(:)
      real :: domain_res, domain_size, base_height
      real :: domain_ulx, domain_uly

      character(len=512),allocatable :: flist(:)
      character(len=512) :: line, ncfile, jsonfile
      character(len=12)  :: stamp
      character(len=32)  :: fmt_top
      character(len=512) :: arg

      integer :: nfile, ifl, ios, p
      integer :: i, j, k
      real    :: c0, c1
      double precision :: tval

      integer :: ncid, did_x, did_y, did_z, did_t
      integer :: vid_x, vid_y, vid_z, vid_t
      integer :: vid_u, vid_v, vid_w, vid_c
      integer :: vid_su, vid_sv, vid_sw, vid_sc
      integer :: d4(4), d3(3)

      allocate(uu(imax2,jmax2,kmax2), vv(imax2,jmax2,kmax2))
      allocate(ww(imax2,jmax2,kmax2), tt(imax2,jmax2,kmax2))
      allocate(ee(imax2,jmax2,kmax2), co(imax2,jmax2,kmax2))
      allocate(ijs(imax2,jmax2,kmax2))

      allocate(u(imax,jmax,kmax), v(imax,jmax,kmax))
      allocate(w(imax,jmax,kmax), c(imax,jmax,kmax))

      allocate(sur_u(imax,jmax), sur_v(imax,jmax))
      allocate(sur_w(imax,jmax), sur_c(imax,jmax))
      allocate(sur_found(imax,jmax))

      allocate(dx(imax2), dy(jmax2), dz(kmax2))
      allocate(px(imax2), py(jmax2), pz(kmax2))
      allocate(x(imax), y(jmax), z(kmax))

      dx = cfd_dx
      dx(1) = 0.
      dx(imax2) = 0.
      dy = cfd_dy
      dy(1) = 0.
      dy(jmax2) = 0.
      dz = cfd_dz
      dz(1) = 0.
      dz(kmax2) = 0.

      px(1) = 0.
      px(2) = 0.5*dx(2)
      do 160 i=3,imax1
  160 px(i) = px(i-1)+(dx(i-1)+dx(i))/2.
      px(imax2) = px(imax1)+0.5*dx(imax1)

      py(1) = 0.
      py(2) = 0.5*dy(2)
      do 170 j=3,jmax1
  170 py(j) = py(j-1)+(dy(j-1)+dy(j))/2.
      py(jmax2) = py(jmax1)+0.5*dy(jmax1)

      pz(1) = 0.
      pz(2) = 0.5*dz(2)
      do 180 k=3,kmax1
  180 pz(k) = pz(k-1)+(dz(k-1)+dz(k))/2.
      pz(kmax2) = pz(kmax1)+0.5*dz(kmax1)

      do i=1,imax
        x(i) = px(i+1)
      enddo
      do j=1,jmax
        y(j) = py(j+1)
      enddo
      do k=1,kmax
        z(k) = pz(k+1)
      enddo

      call read_domain_metadata(domaininfofile)

c#############################################################################
      ijs = 1
      write(fmt_top,'("(",i0,"i1)")') imax2

      open(12,file=topfile,status='old',action='read',iostat=ios)
      if (ios .ne. 0) then
        write(*,*) 'ERROR: cannot open ', trim(topfile)
        stop 1
      endif

      do 900 k=1,ktop1
        read(12,'(a)',iostat=ios) line
        if (ios .ne. 0) then
          write(*,*) 'ERROR: .top truncated at k =', k
          stop 1
        endif
        do 910 j=jmax2,1,-1
  910   read(12,fmt_top) (ijs(i,j,k),i=1,imax2)
  900 continue
      close(12)

      call execute_command_line('mkdir -p '//outdir)
      jsonfile = outdir//'/domain_metadata.json'
      call write_metadata_json(jsonfile)
      write(*,'(a,a)') ' >> metadata json: ', trim(jsonfile)

c#############################################################################
      nfile = command_argument_count()
      if (nfile .gt. 0) then
        allocate(flist(nfile))
        do ifl=1,nfile
          call get_command_argument(ifl,arg)
          flist(ifl) = arg
        enddo
      else
        call execute_command_line('ls -1 '//indir//
     &       '/output_*.dat > .filelist.tmp 2>/dev/null')

        open(13,file='.filelist.tmp',status='old',action='read',
     &       iostat=ios)
        if (ios .ne. 0) then
          write(*,*) 'ERROR: no file list'
          stop 1
        endif

        nfile = 0
  200 read(13,'(a)',iostat=ios) line
        if (ios .eq. 0) then
          if (len_trim(line) .gt. 0) nfile = nfile + 1
          go to 200
        endif

        if (nfile .eq. 0) then
          write(*,*) 'ERROR: no output_*.dat in ', indir
          stop 1
        endif

        allocate(flist(nfile))
        rewind(13)
        ifl = 0
  210 read(13,'(a)',iostat=ios) line
        if (ios .eq. 0) then
          if (len_trim(line) .gt. 0) then
            ifl = ifl + 1
            flist(ifl) = line
          endif
          go to 210
        endif
        close(13)
        call execute_command_line('rm -f .filelist.tmp')
      endif

      write(*,'(a,i0,a)') ' >> ', nfile, ' file(s) found'

      do 1000 ifl=1,nfile

      p = index(flist(ifl),'output_',back=.true.)
      if (p .eq. 0 .or. len_trim(flist(ifl)) .lt. p+18) then
        write(*,*) ' skip (name pattern) : ', trim(flist(ifl))
        go to 1000
      endif
      stamp = flist(ifl)(p+7:p+18)

      call cpu_time(c0)
      write(*,'(a,i0,a,i0,a,a)') ' [',ifl,'/',nfile,'] ',
     &      trim(flist(ifl))

      open(11,file=trim(flist(ifl)),status='old',action='read',
     &     iostat=ios)
      if (ios .ne. 0) then
        write(*,*) '  ! open failed, skip'
        go to 1000
      endif

      ios = 0
      do 6000 k=1,kmax2
      do 6000 j=1,jmax2
      do 6000 i=1,imax2
      read(11,*,iostat=ios) uu(i,j,k), vv(i,j,k), ww(i,j,k),
     &     tt(i,j,k), co(i,j,k), ee(i,j,k)
      if (ios .ne. 0) go to 6010
 6000 continue
 6010 close(11)

      if (ios .ne. 0) then
        write(*,*) '  ! record short / read error, skip'
        go to 1000
      endif

c#############################################################################
      do 300 k=1,kmax
      do 300 j=1,jmax
      do 300 i=1,imax
      u(i,j,k) = (uu(i,j+1,k+1) + uu(i+1,j+1,k+1))/2.
      v(i,j,k) = (vv(i+1,j,k+1) + vv(i+1,j+1,k+1))/2.
      w(i,j,k) = (ww(i+1,j+1,k) + ww(i+1,j+1,k+1))/2.
      c(i,j,k) = co(i+1,j+1,k+1)
  300 continue

c#############################################################################
      sur_u = FILLV
      sur_v = FILLV
      sur_w = FILLV
      sur_c = FILLV
      sur_found = .false.

      do 501 k=1,kmax
      do 501 j=1,jmax
      do 501 i=1,imax
      if ((ijs(i+1,j+1,k)   .eq. 0) .and.
     &    (ijs(i+1,j+1,k+1) .ne. 0)) then
        sur_u(i,j) = u(i,j,k)
        sur_v(i,j) = v(i,j,k)
        sur_w(i,j) = w(i,j,k)
        sur_c(i,j) = c(i,j,k)
        sur_found(i,j) = .true.
      endif
  501 continue

c#############################################################################
      if (mask_solid) then
        do 510 k=1,kmax
        do 510 j=1,jmax
        do 510 i=1,imax
        if (ijs(i+1,j+1,k+1) .eq. 0) then
          u(i,j,k) = FILLV
          v(i,j,k) = FILLV
          w(i,j,k) = FILLV
          c(i,j,k) = FILLV
        endif
  510   continue
      endif

c#############################################################################
      ncfile = outdir//'/output_'//stamp//'.nc'
      call nck(nf90_create(trim(ncfile),
     &     ior(NF90_NETCDF4,NF90_CLOBBER), ncid), 'create')

      call nck(nf90_def_dim(ncid,'x',imax,did_x), 'dim x')
      call nck(nf90_def_dim(ncid,'y',jmax,did_y), 'dim y')
      call nck(nf90_def_dim(ncid,'z',kmax,did_z), 'dim z')
      call nck(nf90_def_dim(ncid,'time',NF90_UNLIMITED,did_t),
     &     'dim time')

      d4 = (/ did_x, did_y, did_z, did_t /)
      d3 = (/ did_x, did_y, did_t /)

      call nck(nf90_def_var(ncid,'x',NF90_REAL,(/did_x/),vid_x),
     &     'var x')
      call putatt(vid_x,'units','m')
      call putatt(vid_x,'long_name','x distance')
      call putatt(vid_x,'axis','X')

      call nck(nf90_def_var(ncid,'y',NF90_REAL,(/did_y/),vid_y),
     &     'var y')
      call putatt(vid_y,'units','m')
      call putatt(vid_y,'long_name','y distance')
      call putatt(vid_y,'axis','Y')

      call nck(nf90_def_var(ncid,'z',NF90_REAL,(/did_z/),vid_z),
     &     'var z')
      call putatt(vid_z,'units','m')
      call putatt(vid_z,'long_name','height above datum')
      call putatt(vid_z,'axis','Z')
      call putatt(vid_z,'positive','up')

      call nck(nf90_def_var(ncid,'time',NF90_DOUBLE,(/did_t/),
     &     vid_t), 'var time')
      call putatt(vid_t,'units',
     &     'minutes since 1970-01-01 00:00:00')
      call putatt(vid_t,'calendar','standard')
      call putatt(vid_t,'axis','T')

      call def3('u', 'm s-1',  'x wind component',   vid_u)
      call def3('v', 'm s-1',  'y wind component',   vid_v)
      call def3('w', 'm s-1',  'vertical wind',       vid_w)
      call def3('c', 'kg m-3', 'concentration',       vid_c)

      call defsurf('sur_u', 'm s-1',
     &     'surface x wind component',     vid_su)
      call defsurf('sur_v', 'm s-1',
     &     'surface y wind component',     vid_sv)
      call defsurf('sur_w', 'm s-1',
     &     'surface vertical wind',        vid_sw)
      call defsurf('sur_c', 'kg m-3',
     &     'surface concentration',        vid_sc)

      call nck(nf90_put_att(ncid,NF90_GLOBAL,'title',
     &     'PARANS CFD post-processed field (u,v,w,c + surface)'),
     &     'att title')
      call nck(nf90_put_att(ncid,NF90_GLOBAL,'source',
     &     'PARANS moment solver'), 'att source')
      call nck(nf90_put_att(ncid,NF90_GLOBAL,'timestamp',stamp),
     &     'att stamp')
      call nck(nf90_put_att(ncid,NF90_GLOBAL,'Conventions',
     &     'CF-1.8'), 'att conv')
      call nck(nf90_enddef(ncid), 'enddef')

      read(stamp(1:4),*)   i
      read(stamp(5:6),*)   j
      read(stamp(7:8),*)   k
      tval = dble(days_from_civil(i,j,k))*1440.d0
      read(stamp(9:10),*)  i
      read(stamp(11:12),*) j
      tval = tval + dble(i)*60.d0 + dble(j)

      call nck(nf90_put_var(ncid,vid_x,x), 'put x')
      call nck(nf90_put_var(ncid,vid_y,y), 'put y')
      call nck(nf90_put_var(ncid,vid_z,z), 'put z')
      call nck(nf90_put_var(ncid,vid_t,(/tval/),start=(/1/),
     &     count=(/1/)), 'put time')

      call p3(vid_u, u)
      call p3(vid_v, v)
      call p3(vid_w, w)
      call p3(vid_c, c)

      call p2(vid_su, sur_u)
      call p2(vid_sv, sur_v)
      call p2(vid_sw, sur_w)
      call p2(vid_sc, sur_c)

      call nck(nf90_close(ncid), 'close')
      call cpu_time(c1)
      write(*,'(a,a,a,f8.1,a)') '      -> ', trim(ncfile),
     &      '  (', c1-c0, ' s)'

 1000 continue

      write(*,*) '>> done'

      contains

      subroutine nck(st, msg)
      integer,intent(in) :: st
      character(len=*),intent(in) :: msg
      if (st .ne. NF90_NOERR) then
        write(*,*) 'NetCDF ERROR [', trim(msg), '] : ',
     &        trim(nf90_strerror(st))
        stop 2
      endif
      end subroutine nck

      subroutine putatt(vid, name, val)
      integer,intent(in) :: vid
      character(len=*),intent(in) :: name, val
      call nck(nf90_put_att(ncid,vid,name,val), 'att '//name)
      end subroutine putatt

      subroutine def3(name, units, lname, vid)
      character(len=*),intent(in) :: name, units, lname
      integer,intent(out) :: vid
      call nck(nf90_def_var(ncid,name,NF90_REAL,d4,vid,
     &     chunksizes=(/imax,jmax,1,1/), shuffle=.true.,
     &     deflate_level=deflate), 'def '//name)
      call nck(nf90_put_att(ncid,vid,'units',units), 'u '//name)
      call nck(nf90_put_att(ncid,vid,'long_name',lname), 'l '//name)
      call nck(nf90_put_att(ncid,vid,'_FillValue',FILLV), 'f '//name)
      end subroutine def3

      subroutine defsurf(name, units, lname, vid)
      character(len=*),intent(in) :: name, units, lname
      integer,intent(out) :: vid
      call nck(nf90_def_var(ncid,name,NF90_REAL,d3,vid,
     &     chunksizes=(/imax,jmax,1/), shuffle=.true.,
     &     deflate_level=deflate), 'def '//name)
      call nck(nf90_put_att(ncid,vid,'units',units), 'u '//name)
      call nck(nf90_put_att(ncid,vid,'long_name',lname), 'l '//name)
      call nck(nf90_put_att(ncid,vid,'_FillValue',FILLV), 'f '//name)
      end subroutine defsurf

      subroutine p3(vid, a)
      integer,intent(in) :: vid
      real,intent(in) :: a(:,:,:)
      call nck(nf90_put_var(ncid,vid,a,start=(/1,1,1,1/),
     &     count=(/imax,jmax,kmax,1/)), 'put3')
      end subroutine p3

      subroutine p2(vid, a)
      integer,intent(in) :: vid
      real,intent(in) :: a(:,:)
      call nck(nf90_put_var(ncid,vid,a,start=(/1,1,1/),
     &     count=(/imax,jmax,1/)), 'put2')
      end subroutine p2

      subroutine read_domain_metadata(meta_path)
      character(len=*),intent(in) :: meta_path
      character(len=64) :: key
      character(len=512) :: text
      real :: rval
      integer :: u, iosm, iosr

      domain_res = cfd_dx
      domain_size = real(imax) * cfd_dx
      base_height = 0.
      domain_ulx = 0.
      domain_uly = 0.

      u = 91
      open(u,file=trim(meta_path),status='old',action='read',
     &     iostat=iosm)
      if (iosm .ne. 0) then
        write(*,*) 'WARN: cannot read ', trim(meta_path)
        return
      endif

 7000 read(u,'(A)',iostat=iosm) text
      if (iosm .ne. 0) go to 7010
      read(text,*,iostat=iosr) key, rval
      if (iosr .eq. 0) then
        select case (trim(key))
        case ('CELLSIZE')
          domain_res = rval
        case ('BASE_HEIGHT_M')
          base_height = rval
        case ('ULx')
          domain_ulx = rval
        case ('ULy')
          domain_uly = rval
        end select
      endif
      go to 7000

 7010 close(u)
      domain_size = real(imax) * domain_res
      end subroutine read_domain_metadata

      subroutine write_metadata_json(meta_json)
      character(len=*),intent(in) :: meta_json
      integer :: u, iosj

      u = 92
      open(u,file=trim(meta_json),status='replace',action='write',
     &     iostat=iosj)
      if (iosj .ne. 0) then
        write(*,*) 'WARN: cannot write ', trim(meta_json)
        return
      endif

      write(u,'(a)') '{'
      write(u,'(a,a,a)') '  "metadata_source": "',
     &     trim(domaininfofile), '",'
      write(u,'(a,f0.6,a)') '  "dx_m": ', domain_res, ','
      write(u,'(a,f0.6,a)') '  "dy_m": ', domain_res, ','
      write(u,'(a,f0.6,a)') '  "dz_m": ', cfd_dz, ','
!      write(u,'(a,i0,a)') '  "nx": ', imax, ','
!      write(u,'(a,i0,a)') '  "ny": ', jmax, ','
!      write(u,'(a,i0,a)') '  "nz": ', kmax, ','
      write(u,'(a,i0,a)') '  "horizontal_grid_count_x": ',
     &     imax, ','
      write(u,'(a,i0,a)') '  "horizontal_grid_count_y": ',
     &     jmax, ','
      write(u,'(a,i0,a)') '  "vertical_grid_count": ', kmax, ','
      write(u,'(a,f0.6,a)') '  "domain_size_m": ',
     &     domain_size, ','
      write(u,'(a,f0.6,a)') '  "vertical_domain_size_m": ',
     &     real(kmax) * cfd_dz, ','
      write(u,'(a,f12.6,a)') '  "base_height_m": ',
     &     base_height, ','
!      write(u,'(a,f0.6,a)') '  "ulx": ', domain_ulx, ','
!      write(u,'(a,f0.6)') '  "uly": ', domain_uly
      write(u,'(a,f0.6,a)') '  "ulx": ',
     &     domain_ulx + 2.0*domain_res, ','
      write(u,'(a,f0.6)') '  "uly": ',
     &     domain_uly - 2.0*domain_res
      write(u,'(a)') '}'
      close(u)
      end subroutine write_metadata_json

      integer function days_from_civil(yy, mm, dd)
      integer,intent(in) :: yy, mm, dd
      integer :: yr, era, yoe, doy, doe
      yr = yy
      if (mm .le. 2) yr = yr - 1
      if (yr .ge. 0) then
        era = yr/400
      else
        era = (yr-399)/400
      endif
      yoe = yr - era*400
      if (mm .gt. 2) then
        doy = (153*(mm-3) + 2)/5 + dd - 1
      else
        doy = (153*(mm+9) + 2)/5 + dd - 1
      endif
      doe = yoe*365 + yoe/4 - yoe/100 + doy
      days_from_civil = era*146097 + doe - 719468
      end function days_from_civil

      END PROGRAM POST_NC_UVWC
