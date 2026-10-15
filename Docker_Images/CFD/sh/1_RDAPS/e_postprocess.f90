!===============================================================
!  Main program : postprocess_main.f90
!  Reads rdaps_dates.txt and LDAPS_point.txt
!===============================================================
program postprocess_main
   implicit none
   call read_date_and_indices()
end program postprocess_main


!===============================================================
!  Read rdaps_dates.txt and LDAPS_point.txt, then process each case
!===============================================================
subroutine read_date_and_indices()
   implicit none
   integer :: yy, mm, dd, HH
   integer :: x, y
   integer :: ios
   character(len=50) :: line
   character(len=20) :: role
   character(len=200) :: datefile, pointfile
   integer :: num_dates, num_points, i, j
   integer :: x_min, x_max, y_min, y_max
   integer :: imax, jmax, lmax
   character(len=200) :: date_list(1000)
   integer :: x_list(1000), y_list(1000)
   character(len=20) :: role_list(1000)

   datefile  = './rdaps_dates.txt'
   pointfile = './RDAPS_point.txt'

   !----- Read date list
   open(10, file=datefile, status='old', iostat=ios)
   if (ios /= 0) then
      print *, 'ERROR: Cannot open ', trim(datefile)
      stop
   end if

   num_dates = 0
   do
      read(10, '(A)', iostat=ios) line
      if (ios /= 0) exit
      if (trim(line) == '' .or. line(1:1) == '#') cycle
      num_dates = num_dates + 1
      date_list(num_dates) = adjustl(line)
   end do
   close(10)

   !----- Read LDAPS grid indices
   open(11, file=pointfile, status='old', iostat=ios)
   if (ios /= 0) then
      print *, 'ERROR: Cannot open ', trim(pointfile)
      stop
   end if

   num_points = 0
   do
      read(11, '(A)', iostat=ios) line
      if (ios /= 0) exit
      if (trim(line) == '' .or. line(1:1) == '#') cycle
      role = 'interior'
      read(line, *, iostat=ios) x, y
      if (ios /= 0) cycle
      call parse_point_role(line, role)
      num_points = num_points + 1
      x_list(num_points) = x
      y_list(num_points) = y
      role_list(num_points) = role
   end do
   close(11)

   !----- Calculate actual grid span counts
   x_min = minval(x_list(1:num_points))
   x_max = maxval(x_list(1:num_points))
   y_min = minval(y_list(1:num_points))
   y_max = maxval(y_list(1:num_points))

   !----- Calculate grid size
   imax = x_max - x_min + 1
   jmax = y_max - y_min + 1
   lmax = num_points

!   print *, '[INFO] Dates read  =', num_dates
!   print *, '[INFO] Points read =', num_points
!   print *, '[INFO] imax, jmax, lmax =', imax, jmax, lmax

   !----- Loop over dates and points
   do i = 1, num_dates
      read(date_list(i), '(I4,1X,I2,1X,I2,1X,I2)') yy, mm, dd, HH

      do j = 1, num_points
         call convert_temperature(yy, mm, dd, HH, x_list(j), y_list(j))
         call convert_uv_interpolation(yy, mm, dd, HH, x_list(j), y_list(j))
      end do

      if (i == 1) then
         call make_ini_from_vertical_data(yy, mm, dd, HH, x_list, y_list,&
              imax, jmax,lmax)
         call run_horizontal_interpolation(yy, mm, dd, HH, imax, jmax, x_min, y_min)
         call update_moment_namelist_wrf_files(yy, mm, dd, HH)
      else
         call write_boundary_from_vertical_data(yy, mm, dd, HH, x_list, y_list, &
              role_list, lmax)
         call write_top_from_raw_data(yy, mm, dd, HH, x_list, y_list, lmax)
      end if
   end do


end subroutine read_date_and_indices


!===============================================================
!  Parse optional fifth column in RDAPS_point.txt
!===============================================================
subroutine parse_point_role(line, role)
   implicit none
   character(len=*), intent(in) :: line
   character(len=*), intent(out) :: role
   integer :: x, y, ios
   real :: lon, lat
   character(len=20) :: role_tmp

   role = 'interior'
   read(line, *, iostat=ios) x, y, lon, lat, role_tmp
   if (ios == 0) role = adjustl(role_tmp)
end subroutine parse_point_role


!===============================================================
!  Update 2_moment/input.namelist to use dated first-time RDAPS files
!===============================================================
subroutine update_moment_namelist_wrf_files(yy, mm, dd, HH)
   implicit none
   integer, intent(in) :: yy, mm, dd, HH
   integer :: ios
   character(len=500) :: line
   character(len=500) :: namelist_path, tmp_path
   character(len=500) :: u_path, v_path, t_path

   namelist_path = '../2_moment/input.namelist'
   tmp_path = '../2_moment/input.namelist.tmp'

   write(u_path,'(a,i4,3i2.2,a)') "../1_RDAPS/txt_results/", yy, mm, dd, HH, "_u.dat"
   write(v_path,'(a,i4,3i2.2,a)') "../1_RDAPS/txt_results/", yy, mm, dd, HH, "_v.dat"
   write(t_path,'(a,i4,3i2.2,a)') "../1_RDAPS/txt_results/", yy, mm, dd, HH, "_tmp.dat"

   open(91, file=namelist_path, status='old', action='read', iostat=ios)
   if (ios /= 0) return
   open(92, file=tmp_path, status='replace', action='write')

   do
      read(91, '(A)', iostat=ios) line
      if (ios /= 0) exit

      if (index(adjustl(line), 'WRF_U') == 1) then
         write(92,'(A)') "WRF_U   = '" // trim(u_path) // "'"
      else if (index(adjustl(line), 'WRF_V') == 1) then
         write(92,'(A)') "WRF_V   = '" // trim(v_path) // "'"
      else if (index(adjustl(line), 'WRF_T') == 1) then
         write(92,'(A)') "WRF_T   = '" // trim(t_path) // "'"
      else
         write(92,'(A)') trim(line)
      end if
   end do

   close(91)
   close(92)
   call execute_command_line('mv ../2_moment/input.namelist.tmp ../2_moment/input.namelist')
end subroutine update_moment_namelist_wrf_files


!===============================================================
!  Convert temperature
!===============================================================
subroutine convert_temperature(yy, mm, dd, HH, x, y)
   implicit none
   integer, intent(in) :: yy, mm, dd, HH, x, y
   include '../data/Domain/rdaps_domain.inc'
   integer, parameter :: kmax2 = cfd_kmax2
   integer, parameter :: kmax1 = cfd_kmax1
   integer, parameter :: max_hgt = 100
   real, parameter :: hgt_cover_tol = 1.0e-3
   real, allocatable :: height(:)
   real, allocatable :: temp(:), geo_value(:)
   real :: dz(kmax2), pz(kmax2), new_po(kmax2), new_value(kmax2)
   real :: hgt_raw(max_hgt)
   integer :: i, j, kk, ios, n_hgt, num_layer_out
   character(len=2000) :: ifile, ofile, hgtfile
   character(len=3) :: uv

   uv = 'tmp'

   !----- Read height file
   write(hgtfile,'("./txt/",I0,"_",I0,"_",I4.4,3I2.2,"_hgt.txt")') &
        x, y, yy, mm, dd, HH

   open(43, file=hgtfile, status='old', action='read', iostat=ios)
   if (ios /= 0) then
      print *, 'ERROR: Cannot open height file ', trim(hgtfile)
      stop
   end if

   n_hgt = 0
   do
      read(43, *, iostat=ios) hgt_raw(n_hgt+1)
      if (ios /= 0) exit
      n_hgt = n_hgt + 1
      if (n_hgt >= max_hgt) exit
   end do
   close(43)

   !----- Build height array up to first level > CFD domain top
   num_layer_out = 1
   allocate(height(n_hgt+1))
   height(1) = 0.0

   do i = 1, n_hgt
      num_layer_out = num_layer_out + 1
      height(num_layer_out) = hgt_raw(i)

      if (hgt_raw(i) >= cfd_zmax - hgt_cover_tol) exit
   end do
   if (height(num_layer_out) < cfd_zmax - hgt_cover_tol) then
      print *, 'ERROR: HGT levels do not cover CFD top height ', cfd_zmax
      print *, '       file=', trim(hgtfile), ' max_hgt=', height(num_layer_out)
      error stop 1
   end if

   !----- Allocate arrays
   allocate(temp(num_layer_out))
   allocate(geo_value(num_layer_out))

   !----- File paths (safe free-form)
   write(ifile,'(A,"/",I0,"_",I0,"_",I4.4,3I2.2,"_",A,".txt")') &
      './txt', x, y, yy, mm, dd, HH, trim(uv)
   write(ofile,'(A,"/",I0,"_",I0,"_",I4.4,3I2.2,"_",A,".txt")') &
      './txt_vertical_interpolation', x, y, yy, mm, dd, HH, trim(uv)

   open(41, file=ifile, status='old', action='read')
   open(42, file=ofile, status='unknown', action='write')

   do i = 2, num_layer_out
      read(41, *) temp(i)
   end do

   !----- NC pressure-level TMP is Kelvin; MOMENT expects Celsius.
   do i = 2, num_layer_out
      temp(i) = temp(i) - 273.15
   end do

   !----- Vertical grid
   do kk = 1, kmax2
      dz(kk) = cfd_dz
   end do
   dz(1) = 0.0
   dz(kmax2) = 0.0

   pz(1) = 0.0
   pz(2) = 0.5 * dz(2)
   do kk = 3, kmax1
      pz(kk) = pz(kk-1) + (dz(kk-1)+dz(kk))/2.0
   end do
   pz(kmax2) = pz(kmax1) + 0.5 * dz(kmax1)
   new_po = pz
   geo_value = temp

   !----- Interpolation
   do j = 2, num_layer_out - 1
      do i = 1, kmax2
         if (new_po(i) .eq. height(j)) then
            new_value(i) = geo_value(j)
         end if

         if (new_po(i) >= height(j) .and. new_po(i) <= height(j+1)) then
            new_value(i) = (((new_po(i)-height(j))*geo_value(j+1)) + &
                           ((height(j+1)-new_po(i))*geo_value(j))) / &
                           (height(j+1)-height(j))
         elseif (new_po(i) < height(2)) then
            new_value(i) = geo_value(2)
         end if
      end do
   end do

   !----- Output
   do i = 1, kmax2
      write(42,*) new_value(i)
   end do

100 continue
   close(41)
   close(42)

   deallocate(height, temp, geo_value)

end subroutine convert_temperature


!===============================================================
!  Interpolate u, v (LDAPS to CFD vertical grid)
!===============================================================
subroutine convert_uv_interpolation(yy, mm, dd, HH, x, y)
   implicit none
   integer, intent(in) :: yy, mm, dd, HH, x, y
   include '../data/Domain/rdaps_domain.inc'
   integer, parameter :: kmax2 = cfd_kmax2
   integer, parameter :: kmax1 = cfd_kmax1
   integer, parameter :: max_hgt = 100
   real, parameter :: hgt_cover_tol = 1.0e-3
   real, allocatable :: LDAPS(:)
   real :: dz(kmax2), pz(kmax2)
   real, allocatable :: geo_po(:), geo_value(:)
   real :: new_po(kmax2), new_value(kmax2)
   real :: hgt_raw(max_hgt)
   integer :: i, j, kk, var_idx, ios, n_hgt, num_layer_out
   character(len=2000) :: ifile, ofile, hgtfile
   character(len=4) :: uv

   !----- Read height file
   write(hgtfile,'("./txt/",I0,"_",I0,"_",I4.4,3I2.2,"_hgt.txt")') &
        x, y, yy, mm, dd, HH

   open(43, file=hgtfile, status='old', action='read', iostat=ios)
   if (ios /= 0) then
      print *, 'ERROR: Cannot open height file ', trim(hgtfile)
      stop
   end if

   n_hgt = 0
   do
      read(43, *, iostat=ios) hgt_raw(n_hgt+1)
      if (ios /= 0) exit
      n_hgt = n_hgt + 1
      if (n_hgt >= max_hgt) exit
   end do
   close(43)

   !----- Build height array up to first level > CFD domain top
   num_layer_out = 1
   allocate(geo_po(n_hgt+1))
   geo_po(1) = 0.0

   do i = 1, n_hgt
      num_layer_out = num_layer_out + 1
      geo_po(num_layer_out) = hgt_raw(i)

      if (hgt_raw(i) >= cfd_zmax - hgt_cover_tol) exit
   end do
   if (geo_po(num_layer_out) < cfd_zmax - hgt_cover_tol) then
      print *, 'ERROR: HGT levels do not cover CFD top height ', cfd_zmax
      print *, '       file=', trim(hgtfile), ' max_hgt=', geo_po(num_layer_out)
      error stop 1
   end if

   !----- Allocate arrays
   allocate(LDAPS(num_layer_out))
   allocate(geo_value(num_layer_out))

   !----- Loop for 'u' and 'v' components
   do var_idx = 1, 2
      if (var_idx == 1) then
         uv = 'u'
      else
         uv = 'v'
      end if

      write(ifile,'(A,"/",I0,"_",I0,"_",I4.4,3I2.2,"_",A,".txt")') &
         './txt', x, y, yy, mm, dd, HH, trim(uv)
      write(ofile,'(A,"/",I0,"_",I0,"_",I4.4,3I2.2,"_",A,".txt")') &
         './txt_vertical_interpolation', x, y, yy, mm, dd, HH, trim(uv)

      open(41, file=ifile, status='old', action='read')
      open(42, file=ofile, status='unknown', action='write')

      do i = 2, num_layer_out
         read(41, *, end=900) LDAPS(i)
      end do

      do kk = 1, kmax2
         dz(kk) = cfd_dz
      end do
      dz(1) = 0.0
      dz(kmax2) = 0.0

      pz(1) = 0.0
      pz(2) = 0.5 * dz(2)
      do kk = 3, kmax1
         pz(kk) = pz(kk-1) + (dz(kk-1)+dz(kk))/2.0
      end do
      pz(kmax2) = pz(kmax1) + 0.5 * dz(kmax1)
      new_po = pz

      geo_value = 0.0
      do kk = 2, num_layer_out
         geo_value(kk) = LDAPS(kk)
      end do

      !----- Interpolation
      do j = 2, num_layer_out - 1
         do i = 1, kmax2
            if (new_po(i) >= geo_po(j) .and. new_po(i) <= geo_po(j+1))then
               new_value(i) = (((new_po(i)-geo_po(j))*geo_value(j+1)) + &
                              ((geo_po(j+1)-new_po(i))*geo_value(j))) / &
                              (geo_po(j+1)-geo_po(j))
            elseif (new_po(i) < geo_po(2)) then
               new_value(i) = geo_value(2)
            end if
         end do
      end do

      !----- Output
      do i = 1, kmax2
         write(42,'(F12.6)') new_value(i)
      end do

900   continue
      close(41)
      close(42)
   end do

   deallocate(geo_po, LDAPS, geo_value)

end subroutine convert_uv_interpolation

!===============================================================
!  Combine all vertical-interpolated files into 3D domain
!===============================================================
subroutine make_ini_from_vertical_data(yy, mm, dd, HH, x, y, imax, jmax, lmax)
   implicit none
   integer, intent(in) :: yy, mm, dd, HH
   integer, intent(in), dimension(lmax) :: x, y
   integer, intent(in) :: imax, jmax, lmax
   include '../data/Domain/rdaps_domain.inc'
   integer, parameter :: kmax = cfd_kmax2
   character(len=2000) :: ifile1, ifile2, ifile3
   character(len=2000) :: ofile1, ofile2, ofile3
   integer :: i, j, k, ii, jj, l
   real, allocatable :: p_u(:,:,:), p_v(:,:,:), p_t(:,:,:)
   real, allocatable :: LDAPS_u(:,:,:), LDAPS_v(:,:,:), LDAPS_t(:,:,:)
   allocate(p_u(kmax,imax,jmax), p_v(kmax,imax,jmax), p_t(kmax,imax,jmax))
   allocate(LDAPS_u(imax+1,jmax+1,kmax), LDAPS_v(imax+1,jmax+1,kmax),&
           LDAPS_t(imax+1,jmax+1,kmax))


   write(ofile1,'(a,i4,3i2.2,a)') './txt_vertical_interpolation_comb/',&
        yy,mm,dd,HH,'_u.txt'
   write(ofile2,'(a,i4,3i2.2,a)') './txt_vertical_interpolation_comb/',&
        yy,mm,dd,HH,'_v.txt'
   write(ofile3,'(a,i4,3i2.2,a)') './txt_vertical_interpolation_comb/',&
        yy,mm,dd,HH,'_tmp.txt'


   !open(13,file=ofile1,status='unknown')
   !open(14,file=ofile2,status='unknown')
   !open(15,file=ofile3,status='unknown')

   open(13,file=ofile1,status='replace',action='write')
   open(14,file=ofile2,status='replace',action='write')
   open(15,file=ofile3,status='replace',action='write')

   l = 0

   do i = 1,imax
   do j = 1,jmax

    l = l + 1

   write(ifile1,'(A,"/",I0,"_",I0,"_",I4.4,3I2.2,"_","u.txt")')&
      './txt_vertical_interpolation',x(l),y(l),yy,mm,dd,HH
   write(ifile2,'(A,"/",I0,"_",I0,"_",I4.4,3I2.2,"_","v.txt")')&
      './txt_vertical_interpolation',x(l),y(l),yy,mm,dd,HH
   write(ifile3,'(A,"/",I0,"_",I0,"_",I4.4,3I2.2,"_","tmp.txt")')&
      './txt_vertical_interpolation',x(l),y(l),yy,mm,dd,HH


   open(10,file=ifile1,status='old')
   open(11,file=ifile2,status='old')
   open(12,file=ifile3,status='old')

!   do i = 1, imax
!   do j = 1, jmax
   do k = 1, kmax
   read(10,5000) p_u(k,i,j)
   read(11,5000) p_v(k,i,j)
   read(12,5000) p_t(k,i,j)
   enddo

   close(10)
   close(11)
   close(12)
!   enddo 
!   enddo

   end do ! j
   end do ! i

 5000 format(f12.6)

   do i = 1, imax
   do j = jmax,1,-1
   do k=1,kmax
   LDAPS_u(i,j,k)=p_u(k,i,j)
   LDAPS_v(i,j,k)=p_v(k,i,j)
   LDAPS_t(i,j,k)=p_t(k,i,j)
   enddo
   enddo
   enddo

   do k=1,kmax
   do jj=1,jmax
   do ii=1,imax
    write(13,5000) LDAPS_u(ii,jj,k)
    write(14,5000) LDAPS_v(ii,jj,k)
    write(15,5000) LDAPS_t(ii,jj,k)
   enddo
   enddo
   enddo

   close(13)
   close(14)
   close(15)

   deallocate(p_u, p_v, p_t)
   deallocate(LDAPS_u, LDAPS_v, LDAPS_t)


end subroutine make_ini_from_vertical_data


!===============================================================
!  Compute CFD cut indices inside horizontally interpolated RDAPS grid
!===============================================================
subroutine get_cfd_cut_indices(imax, jmax, x_min, y_min, i_sta, j_sta, i_end, j_end)
   implicit none
   integer, intent(in) :: imax, jmax, x_min, y_min
   integer, intent(out) :: i_sta, j_sta, i_end, j_end
   include '../data/Domain/rdaps_domain.inc'
   integer, parameter :: LDAPS_m=3000, dx=cfd_dx, dy=cfd_dy
   integer, parameter :: ip_n = (LDAPS_m/dx)
   integer, parameter :: ilmax=cfd_ilmax, jlmax=cfd_jlmax
   integer :: ifmax, jfmax
   character(len=100) :: label
   character(len=200) :: line, idx_token
   integer :: ios
   integer :: x_idx, y_idx, p1, p2, pc
   real :: val, lat, lon, ldaps_x, ldaps_y
   real :: x_cfd_min, y_cfd_min

   ifmax = ((imax-1)*ip_n + 1)
   jfmax = ((jmax-1)*ip_n + 1)

   open(40, file='../data/Domain/output_model_info.txt', status='old', action='read')
   do
      read(40,*,end=10) label, val
      select case (trim(label))
      case ('XLLCORNER')
         x_cfd_min = val
      case ('YLLCORNER')
         y_cfd_min = val
      end select
   end do
10 close(40)

   open(41, file='./latlon_utmk_output.txt', &
        status='old', action='read')
   do
      read(41,'(A)',iostat=ios) line
      if (ios /= 0) exit
      if (trim(line)=='' .or. line(1:1)=='#') cycle
      if (index(line,'LAT')>0 .and. index(line,'LON')>0) cycle

      read(line,'(A10,2X,F10.6,2X,F10.6,2X,F12.2,2X,F12.2)', iostat=ios) &
           idx_token, lat, lon, ldaps_y, ldaps_x
      if (ios /= 0) cycle

      p1 = index(idx_token,'(')
      pc = index(idx_token,',')
      p2 = index(idx_token,')')
      if (p1==0 .or. pc==0 .or. p2==0) cycle

      read(idx_token(p1+1:pc-1),*,iostat=ios) x_idx
      if (ios /= 0) cycle
      read(idx_token(pc+1:p2-1),*,iostat=ios) y_idx
      if (ios /= 0) cycle

      if (x_idx == x_min .and. y_idx == y_min) exit
   end do
   close(41)

   i_sta = nint((x_cfd_min - ldaps_x) / dx) + 1
   j_sta = nint((y_cfd_min - ldaps_y) / dy) + 1
   i_end = (ilmax - 1) + i_sta
   j_end = (jlmax - 1) + j_sta

   if (i_sta < 1 .or. j_sta < 1 .or. i_end > ifmax .or. j_end > jfmax) then
      print *, 'ERROR: CFD cut indices are outside interpolated RDAPS domain'
      print *, 'i_sta,i_end,ifmax = ', i_sta, i_end, ifmax
      print *, 'j_sta,j_end,jfmax = ', j_sta, j_end, jfmax
      stop
   end if
end subroutine get_cfd_cut_indices


!===============================================================
!  Write later-time side boundary data from vertical interpolation
!===============================================================
subroutine write_boundary_from_vertical_data(yy, mm, dd, HH, x, y, role, lmax)
   implicit none
   integer, intent(in) :: yy, mm, dd, HH, lmax
   integer, intent(in), dimension(lmax) :: x, y
   character(len=*), intent(in), dimension(lmax) :: role
   include '../data/Domain/rdaps_domain.inc'
   integer, parameter :: LDAPS_m=3000, dx=cfd_dx, dy=cfd_dy
   integer, parameter :: kmax = cfd_kmax2
   integer, parameter :: ip_n = (LDAPS_m/dx)
   integer, parameter :: ip_n2 = (ip_n-1)
   integer, parameter :: ilmax=cfd_ilmax, jlmax=cfd_jlmax
   integer :: l, k, ios, ii, jj
   integer :: x_min, x_max, y_min, y_max
   integer :: imax, jmax, ifmax, jfmax, i_sta, j_sta, i_end, j_end
   integer :: p, p0, p1
   real :: uval, vval, tval, n
   character(len=2000) :: ifile_u, ifile_v, ifile_t
   character(len=2000) :: ofile
   real, allocatable :: west_u(:,:), west_v(:,:), west_t(:,:)
   real, allocatable :: east_u(:,:), east_v(:,:), east_t(:,:)
   real, allocatable :: south_u(:,:), south_v(:,:), south_t(:,:)
   real, allocatable :: north_u(:,:), north_v(:,:), north_t(:,:)
   real, allocatable :: west_uu(:,:), west_vv(:,:), west_tt(:,:)
   real, allocatable :: east_uu(:,:), east_vv(:,:), east_tt(:,:)
   real, allocatable :: south_uu(:,:), south_vv(:,:), south_tt(:,:)
   real, allocatable :: north_uu(:,:), north_vv(:,:), north_tt(:,:)

   x_min = minval(x(1:lmax))
   x_max = maxval(x(1:lmax))
   y_min = minval(y(1:lmax))
   y_max = maxval(y(1:lmax))
   imax = x_max - x_min + 1
   jmax = y_max - y_min + 1
   ifmax = ((imax-1)*ip_n + 1)
   jfmax = ((jmax-1)*ip_n + 1)

   call get_cfd_cut_indices(imax, jmax, x_min, y_min, i_sta, j_sta, i_end, j_end)

   allocate(west_u(jmax,kmax), west_v(jmax,kmax), west_t(jmax,kmax))
   allocate(east_u(jmax,kmax), east_v(jmax,kmax), east_t(jmax,kmax))
   allocate(south_u(imax,kmax), south_v(imax,kmax), south_t(imax,kmax))
   allocate(north_u(imax,kmax), north_v(imax,kmax), north_t(imax,kmax))
   allocate(west_uu(jfmax,kmax), west_vv(jfmax,kmax), west_tt(jfmax,kmax))
   allocate(east_uu(jfmax,kmax), east_vv(jfmax,kmax), east_tt(jfmax,kmax))
   allocate(south_uu(ifmax,kmax), south_vv(ifmax,kmax), south_tt(ifmax,kmax))
   allocate(north_uu(ifmax,kmax), north_vv(ifmax,kmax), north_tt(ifmax,kmax))

   west_u = 0.0; west_v = 0.0; west_t = 0.0
   east_u = 0.0; east_v = 0.0; east_t = 0.0
   south_u = 0.0; south_v = 0.0; south_t = 0.0
   north_u = 0.0; north_v = 0.0; north_t = 0.0

   do l = 1, lmax
      if (trim(role(l)) /= 'boundary') cycle

      write(ifile_u,'(A,"/",I0,"_",I0,"_",I4.4,3I2.2,"_u.txt")') &
         './txt_vertical_interpolation', x(l), y(l), yy, mm, dd, HH
      write(ifile_v,'(A,"/",I0,"_",I0,"_",I4.4,3I2.2,"_v.txt")') &
         './txt_vertical_interpolation', x(l), y(l), yy, mm, dd, HH
      write(ifile_t,'(A,"/",I0,"_",I0,"_",I4.4,3I2.2,"_tmp.txt")') &
         './txt_vertical_interpolation', x(l), y(l), yy, mm, dd, HH

      open(61, file=ifile_u, status='old', action='read', iostat=ios)
      if (ios /= 0) cycle
      open(62, file=ifile_v, status='old', action='read', iostat=ios)
      if (ios /= 0) then
         close(61)
         cycle
      end if
      open(63, file=ifile_t, status='old', action='read', iostat=ios)
      if (ios /= 0) then
         close(61)
         close(62)
         cycle
      end if

      do k = 1, kmax
         read(61, *, iostat=ios) uval
         if (ios /= 0) exit
         read(62, *, iostat=ios) vval
         if (ios /= 0) exit
         read(63, *, iostat=ios) tval
         if (ios /= 0) exit

         if (x(l) == x_min) then
            west_u(y(l)-y_min+1,k) = uval
            west_v(y(l)-y_min+1,k) = vval
            west_t(y(l)-y_min+1,k) = tval
         end if
         if (x(l) == x_max) then
            east_u(y(l)-y_min+1,k) = uval
            east_v(y(l)-y_min+1,k) = vval
            east_t(y(l)-y_min+1,k) = tval
         end if
         if (y(l) == y_min) then
            south_u(x(l)-x_min+1,k) = uval
            south_v(x(l)-x_min+1,k) = vval
            south_t(x(l)-x_min+1,k) = tval
         end if
         if (y(l) == y_max) then
            north_u(x(l)-x_min+1,k) = uval
            north_v(x(l)-x_min+1,k) = vval
            north_t(x(l)-x_min+1,k) = tval
         end if
      end do

      close(61)
      close(62)
      close(63)
   end do

   west_uu = 0.0; west_vv = 0.0; west_tt = 0.0
   east_uu = 0.0; east_vv = 0.0; east_tt = 0.0
   do k = 1, kmax
      do p = 1, jmax
         p0 = p*ip_n - ip_n2
         west_uu(p0,k) = west_u(p,k); west_vv(p0,k) = west_v(p,k); west_tt(p0,k) = west_t(p,k)
         east_uu(p0,k) = east_u(p,k); east_vv(p0,k) = east_v(p,k); east_tt(p0,k) = east_t(p,k)
      end do
      do p = 1, jmax - 1
         p0 = p*ip_n - ip_n2
         p1 = p0 + ip_n
         n = 0.0
         do jj = 1, ip_n2
            n = n + 1.0
            west_uu(p0+jj,k)=west_uu(p0,k)+((west_uu(p1,k)-west_uu(p0,k))*(n/ip_n))
            west_vv(p0+jj,k)=west_vv(p0,k)+((west_vv(p1,k)-west_vv(p0,k))*(n/ip_n))
            west_tt(p0+jj,k)=west_tt(p0,k)+((west_tt(p1,k)-west_tt(p0,k))*(n/ip_n))
            east_uu(p0+jj,k)=east_uu(p0,k)+((east_uu(p1,k)-east_uu(p0,k))*(n/ip_n))
            east_vv(p0+jj,k)=east_vv(p0,k)+((east_vv(p1,k)-east_vv(p0,k))*(n/ip_n))
            east_tt(p0+jj,k)=east_tt(p0,k)+((east_tt(p1,k)-east_tt(p0,k))*(n/ip_n))
         end do
      end do
   end do

   south_uu = 0.0; south_vv = 0.0; south_tt = 0.0
   north_uu = 0.0; north_vv = 0.0; north_tt = 0.0
   do k = 1, kmax
      do p = 1, imax
         p0 = p*ip_n - ip_n2
         south_uu(p0,k) = south_u(p,k); south_vv(p0,k) = south_v(p,k); south_tt(p0,k) = south_t(p,k)
         north_uu(p0,k) = north_u(p,k); north_vv(p0,k) = north_v(p,k); north_tt(p0,k) = north_t(p,k)
      end do
      do p = 1, imax - 1
         p0 = p*ip_n - ip_n2
         p1 = p0 + ip_n
         n = 0.0
         do ii = 1, ip_n2
            n = n + 1.0
            south_uu(p0+ii,k)=south_uu(p0,k)+((south_uu(p1,k)-south_uu(p0,k))*(n/ip_n))
            south_vv(p0+ii,k)=south_vv(p0,k)+((south_vv(p1,k)-south_vv(p0,k))*(n/ip_n))
            south_tt(p0+ii,k)=south_tt(p0,k)+((south_tt(p1,k)-south_tt(p0,k))*(n/ip_n))
            north_uu(p0+ii,k)=north_uu(p0,k)+((north_uu(p1,k)-north_uu(p0,k))*(n/ip_n))
            north_vv(p0+ii,k)=north_vv(p0,k)+((north_vv(p1,k)-north_vv(p0,k))*(n/ip_n))
            north_tt(p0+ii,k)=north_tt(p0,k)+((north_tt(p1,k)-north_tt(p0,k))*(n/ip_n))
         end do
      end do
   end do

   write(ofile,'(a,i4,3i2.2,a)') './txt_results/boundary_', yy, mm, dd, HH, '_west_u.dat'
   open(51, file=ofile, status='replace')
   write(ofile,'(a,i4,3i2.2,a)') './txt_results/boundary_', yy, mm, dd, HH, '_west_v.dat'
   open(52, file=ofile, status='replace')
   write(ofile,'(a,i4,3i2.2,a)') './txt_results/boundary_', yy, mm, dd, HH, '_west_tmp.dat'
   open(53, file=ofile, status='replace')
   write(ofile,'(a,i4,3i2.2,a)') './txt_results/boundary_', yy, mm, dd, HH, '_east_u.dat'
   open(54, file=ofile, status='replace')
   write(ofile,'(a,i4,3i2.2,a)') './txt_results/boundary_', yy, mm, dd, HH, '_east_v.dat'
   open(55, file=ofile, status='replace')
   write(ofile,'(a,i4,3i2.2,a)') './txt_results/boundary_', yy, mm, dd, HH, '_east_tmp.dat'
   open(56, file=ofile, status='replace')
   write(ofile,'(a,i4,3i2.2,a)') './txt_results/boundary_', yy, mm, dd, HH, '_south_u.dat'
   open(57, file=ofile, status='replace')
   write(ofile,'(a,i4,3i2.2,a)') './txt_results/boundary_', yy, mm, dd, HH, '_south_v.dat'
   open(58, file=ofile, status='replace')
   write(ofile,'(a,i4,3i2.2,a)') './txt_results/boundary_', yy, mm, dd, HH, '_south_tmp.dat'
   open(59, file=ofile, status='replace')
   write(ofile,'(a,i4,3i2.2,a)') './txt_results/boundary_', yy, mm, dd, HH, '_north_u.dat'
   open(70, file=ofile, status='replace')
   write(ofile,'(a,i4,3i2.2,a)') './txt_results/boundary_', yy, mm, dd, HH, '_north_v.dat'
   open(71, file=ofile, status='replace')
   write(ofile,'(a,i4,3i2.2,a)') './txt_results/boundary_', yy, mm, dd, HH, '_north_tmp.dat'
   open(72, file=ofile, status='replace')

   do k = 1, kmax
      do jj = 1, jlmax
         p0 = j_sta + jj - 1
         write(51,'(I0,1X,I0,1X,I0,1X,F12.6)') 1, jj, k, west_uu(p0,k)
         write(52,'(I0,1X,I0,1X,I0,1X,F12.6)') 1, jj, k, west_vv(p0,k)
         write(53,'(I0,1X,I0,1X,I0,1X,F12.6)') 1, jj, k, west_tt(p0,k)
         write(54,'(I0,1X,I0,1X,I0,1X,F12.6)') ilmax, jj, k, east_uu(p0,k)
         write(55,'(I0,1X,I0,1X,I0,1X,F12.6)') ilmax, jj, k, east_vv(p0,k)
         write(56,'(I0,1X,I0,1X,I0,1X,F12.6)') ilmax, jj, k, east_tt(p0,k)
      end do
      do ii = 1, ilmax
         p0 = i_sta + ii - 1
         write(57,'(I0,1X,I0,1X,I0,1X,F12.6)') ii, 1, k, south_uu(p0,k)
         write(58,'(I0,1X,I0,1X,I0,1X,F12.6)') ii, 1, k, south_vv(p0,k)
         write(59,'(I0,1X,I0,1X,I0,1X,F12.6)') ii, 1, k, south_tt(p0,k)
         write(70,'(I0,1X,I0,1X,I0,1X,F12.6)') ii, jlmax, k, north_uu(p0,k)
         write(71,'(I0,1X,I0,1X,I0,1X,F12.6)') ii, jlmax, k, north_vv(p0,k)
         write(72,'(I0,1X,I0,1X,I0,1X,F12.6)') ii, jlmax, k, north_tt(p0,k)
      end do
   end do

   close(51)
   close(52)
   close(53)
   close(54)
   close(55)
   close(56)
   close(57)
   close(58)
   close(59)
   close(70)
   close(71)
   close(72)
   deallocate(west_u, west_v, west_t, east_u, east_v, east_t)
   deallocate(south_u, south_v, south_t, north_u, north_v, north_t)
   deallocate(west_uu, west_vv, west_tt, east_uu, east_vv, east_tt)
   deallocate(south_uu, south_vv, south_tt, north_uu, north_vv, north_tt)
end subroutine write_boundary_from_vertical_data


!===============================================================
!  Write later-time top-face data on CFD grid, highest model layer only
!===============================================================
subroutine write_top_from_raw_data(yy, mm, dd, HH, x, y, lmax)
   implicit none
   integer, intent(in) :: yy, mm, dd, HH, lmax
   integer, intent(in), dimension(lmax) :: x, y
   include '../data/Domain/rdaps_domain.inc'
   integer, parameter :: LDAPS_m=3000, dx=cfd_dx, dy=cfd_dy
   integer, parameter :: ip_n = (LDAPS_m/dx)
   integer, parameter :: ip_n2 = (ip_n-1)
   integer, parameter :: ilmax=cfd_ilmax, jlmax=cfd_jlmax
   integer, parameter :: ktop = cfd_kmax2
   integer :: l, var_idx, ios, out_unit
   integer :: x_min, x_max, y_min, y_max
   integer :: imax, jmax, ifmax, jfmax, ifmax2, jfmax2
   integer :: i, j, ii, jj, i_sta, j_sta, i_end, j_end
   integer :: chosen_idx
   real :: val, n
   real :: var_vals(2), hgt_vals(2)
   real, allocatable :: raw(:,:), interp(:,:)
   character(len=4) :: var
   character(len=2000) :: ifile, hgtfile, ofile

   x_min = minval(x(1:lmax))
   x_max = maxval(x(1:lmax))
   y_min = minval(y(1:lmax))
   y_max = maxval(y(1:lmax))
   imax = x_max - x_min + 1
   jmax = y_max - y_min + 1
   ifmax = ((imax-1)*ip_n + 1)
   jfmax = ((jmax-1)*ip_n + 1)
   ifmax2 = ((imax-2)*ip_n + 1)
   jfmax2 = ((jmax-2)*ip_n + 1)

   call get_cfd_cut_indices(imax, jmax, x_min, y_min, i_sta, j_sta, i_end, j_end)
   allocate(raw(imax,jmax), interp(ifmax,jfmax))

   do var_idx = 1, 3
      select case (var_idx)
      case (1)
         var = 'u'
      case (2)
         var = 'v'
      case (3)
         var = 'tmp'
      end select

      out_unit = 80 + var_idx
      write(ofile,'(a,i4,3i2.2,a,a,a)') './txt_results/top_', yy, mm, dd, HH, '_', trim(var), '.dat'
      open(out_unit, file=ofile, status='replace')

      raw = 0.0
      interp = 0.0

      do l = 1, lmax
         write(ifile,'(A,"/",I0,"_",I0,"_",I4.4,3I2.2,"_",A,".txt")') &
            './txt', x(l), y(l), yy, mm, dd, HH, trim(var)
         write(hgtfile,'(A,"/",I0,"_",I0,"_",I4.4,3I2.2,"_hgt.txt")') &
            './txt', x(l), y(l), yy, mm, dd, HH

         if (trim(var) == 'tmp') then
            write(ifile,'(A,"/",I0,"_",I0,"_",I4.4,3I2.2,"_",A,".txt")') &
               './txt_vertical_interpolation', x(l), y(l), yy, mm, dd, HH, trim(var)
            call read_last_value(ifile, var_vals(1), ios)
            if (ios /= 0) cycle
            raw(x(l)-x_min+1, y(l)-y_min+1) = var_vals(1)
         else
            call read_last_two_values(ifile, var_vals, ios)
            if (ios /= 0) cycle
            call read_last_two_values(hgtfile, hgt_vals, ios)
            if (ios /= 0) cycle

            if (abs(hgt_vals(1) - cfd_zmax) <= abs(hgt_vals(2) - cfd_zmax)) then
               chosen_idx = 1
            else
               chosen_idx = 2
            end if

            raw(x(l)-x_min+1, y(l)-y_min+1) = var_vals(chosen_idx)
         end if
      end do

      do j = 1, jmax
         do i = 1, imax
            interp(i*ip_n-ip_n2,j*ip_n-ip_n2) = raw(i,j)
         end do
      end do

      do j = 1, jfmax, ip_n
         do i = 1, ifmax2, ip_n
            n = 0.0
            do l = 1, ip_n2
               n = n + 1.0
               interp(i+l,j) = interp(i,j) + ((interp(i+ip_n,j)-interp(i,j))*(n/ip_n))
            end do
         end do
      end do

      do j = 1, jfmax2, ip_n
         do i = 1, ifmax
            n = 0.0
            do l = 1, ip_n2
               n = n + 1.0
               interp(i,j+l) = interp(i,j) + ((interp(i,j+ip_n)-interp(i,j))*(n/ip_n))
            end do
         end do
      end do

      do jj = 1, jlmax
         do ii = 1, ilmax
            write(out_unit,'(I0,1X,I0,1X,I0,1X,F12.6)') &
               ii, jj, ktop, interp(i_sta+ii-1,j_sta+jj-1)
         end do
      end do

      close(out_unit)
   end do
   deallocate(raw, interp)
end subroutine write_top_from_raw_data


!===============================================================
!  Read the last numeric value from a single-column text file
!===============================================================
subroutine read_last_value(path, val_out, ios_out)
   implicit none
   character(len=*), intent(in) :: path
   real, intent(out) :: val_out
   integer, intent(out) :: ios_out
   integer :: ios, n
   real :: val

   val_out = 0.0
   ios_out = 0
   n = 0

   open(94, file=path, status='old', action='read', iostat=ios)
   if (ios /= 0) then
      ios_out = ios
      return
   end if

   do
      read(94, *, iostat=ios) val
      if (ios /= 0) exit
      n = n + 1
      val_out = val
   end do
   close(94)

   if (n < 1) ios_out = 1
end subroutine read_last_value


!===============================================================
!  Read the last two numeric values from a single-column text file
!===============================================================
subroutine read_last_two_values(path, vals, ios_out)
   implicit none
   character(len=*), intent(in) :: path
   real, intent(out) :: vals(2)
   integer, intent(out) :: ios_out
   integer :: ios, n
   real :: val, prev, curr

   vals = 0.0
   ios_out = 0
   n = 0
   prev = 0.0
   curr = 0.0

   open(93, file=path, status='old', action='read', iostat=ios)
   if (ios /= 0) then
      ios_out = ios
      return
   end if

   do
      read(93, *, iostat=ios) val
      if (ios /= 0) exit
      n = n + 1
      prev = curr
      curr = val
   end do
   close(93)

   if (n < 2) then
      ios_out = 1
      return
   end if

   vals(1) = prev
   vals(2) = curr
end subroutine read_last_two_values


!===============================================================
!  Run horizontal interpolation 
!  Called automatically after make_ini_from_vertical_data()
!===============================================================
subroutine run_horizontal_interpolation(yy, mm, dd, HH, imax, jmax, x_min, y_min)
   implicit none
   integer, intent(in) :: yy, mm, dd, HH
   integer, intent(in) :: imax, jmax
   integer, intent(in) :: x_min, y_min

   !----- CFD and interpolation parameters -----
   include '../data/Domain/rdaps_domain.inc'
   integer, parameter :: LDAPS_m=3000, dx=cfd_dx, dy=cfd_dy
   integer, parameter :: kmax = cfd_kmax2
   integer, parameter :: ip_n = (LDAPS_m/dx)
   integer, parameter :: ip_n2 = (ip_n-1)
   integer :: ifmax, jfmax, ifmax2, jfmax2
   integer, parameter :: ilmax=cfd_ilmax, jlmax=cfd_jlmax

   !----- Variables -----
   real, allocatable :: u(:,:,:), v(:,:,:), t(:,:,:)
   real, allocatable :: uu(:,:,:), vv(:,:,:), tt(:,:,:)
   integer :: i, j, k, l
   integer :: i_sta, j_sta, i_end, j_end
   real :: n
   character(len=2000) :: file1,file2,file3
   character(len=2000) :: file5,file6,file7

   character(len=100) :: label
   character(len=200) :: line, idx_token
   integer :: ios,iostat
   integer :: x_idx, y_idx, p1, p2, pc
   real :: val, lat, lon, ldaps_x, ldaps_y
   real :: x_cfd_min, y_cfd_min


   ifmax  = ((imax-1)*ip_n + 1)
   jfmax  = ((jmax-1)*ip_n + 1)
   ifmax2 = ((imax-2)*ip_n + 1)
   jfmax2 = ((jmax-2)*ip_n + 1)


   allocate(u(imax,jmax,kmax))
   allocate(v(imax,jmax,kmax))
   allocate(t(imax,jmax,kmax))
   allocate(uu(ifmax,jfmax,kmax))
   allocate(vv(ifmax,jfmax,kmax))
   allocate(tt(ifmax,jfmax,kmax))

!   print *, '[INFO] Running horizontal interpolation...'

   !-------------------------------------------------------------
   ! Input files (from make_ini output)
   !-------------------------------------------------------------
   write(file1,'(a,i4,3i2.2,a)') './txt_vertical_interpolation_comb/',yy,mm,dd,HH,'_u.txt'
   write(file2,'(a,i4,3i2.2,a)') './txt_vertical_interpolation_comb/',yy,mm,dd,HH,'_v.txt'
   write(file3,'(a,i4,3i2.2,a)') './txt_vertical_interpolation_comb/',yy,mm,dd,HH,'_tmp.txt'

   open(10,file=file1,status='old')
   open(20,file=file2,status='old')
   open(30,file=file3,status='old')

   do k=1,kmax
      do j=1,jmax
         do i=1,imax
            read(10,5000) u(i,j,k)
            read(20,5000) v(i,j,k)
            read(30,5000) t(i,j,k)
         end do
      end do
   end do
 5000 format(f12.6)
   close(10); close(20); close(30)

   !-------------------------------------------------------------
   ! Initialize arrays
   !-------------------------------------------------------------
   uu = 0.0
   vv = 0.0
   tt = 0.0

   do k=1,kmax
      do j=1,jmax
         do i=1,imax
            uu(i*ip_n-ip_n2,j*ip_n-ip_n2,k) = u(i,j,k)
            vv(i*ip_n-ip_n2,j*ip_n-ip_n2,k) = v(i,j,k)
            tt(i*ip_n-ip_n2,j*ip_n-ip_n2,k) = t(i,j,k)
         end do
      end do
   end do

   !-------------------------------------------------------------
   ! Interpolation in X direction
   !-------------------------------------------------------------
   do k=1,kmax
      do j=1,jfmax,ip_n
         do i=1,ifmax2,ip_n
            n=0.
            do l=1,ip_n2
               n = n+1.
               uu(i+l,j,k)=uu(i,j,k)+((uu(i+ip_n,j,k)-uu(i,j,k))*(n/ip_n))
               vv(i+l,j,k)=vv(i,j,k)+((vv(i+ip_n,j,k)-vv(i,j,k))*(n/ip_n))
               tt(i+l,j,k)=tt(i,j,k)+((tt(i+ip_n,j,k)-tt(i,j,k))*(n/ip_n))
            end do
         end do
      end do
   end do


   !-------------------------------------------------------------
   ! Interpolation in Y direction
   !-------------------------------------------------------------
   do k=1,kmax
      do j=1,jfmax2,ip_n
         do i=1,ifmax
            n=0.
            do l=1,ip_n2
               n = n+1.
               uu(i,j+l,k)=uu(i,j,k)+((uu(i,j+ip_n,k)-uu(i,j,k))*(n/ip_n))
               vv(i,j+l,k)=vv(i,j,k)+((vv(i,j+ip_n,k)-vv(i,j,k))*(n/ip_n))
               tt(i,j+l,k)=tt(i,j,k)+((tt(i,j+ip_n,k)-tt(i,j,k))*(n/ip_n))
            end do
         end do
      end do
   end do

   !-------------------------------------------------------------
   ! Output results (for CFD domain)
   !-------------------------------------------------------------
   write(file5,'(a,i4,3i2.2,a)') './txt_results/', yy, mm, dd, HH, '_u.dat'
   write(file6,'(a,i4,3i2.2,a)') './txt_results/', yy, mm, dd, HH, '_v.dat'
   write(file7,'(a,i4,3i2.2,a)') './txt_results/', yy, mm, dd, HH, '_tmp.dat'

   open(11,file=file5,status='replace')
   open(12,file=file6,status='replace')
   open(13,file=file7,status='replace')

   !-------------------------------------------------------------
   ! CFD domain lower-left corner from output_model_info.txt
   !-------------------------------------------------------------
   open(40, file='../data/Domain/output_model_info.txt', status='old', action='read')
   do
   read(40,*,end=10) label, val
   select case (trim(label))
   case ('XLLCORNER')
      x_cfd_min = val
   case ('YLLCORNER')
      y_cfd_min = val
   end select
   end do
10 close(40)

!   print *, '[INFO] CFD lower-left (XLL, YLL):', x_cfd_min, y_cfd_min

   !-------------------------------------------------------------
   ! LDAPS domain lower-left corner
   !-------------------------------------------------------------
   open(41, file='./latlon_utmk_output.txt', &
   status='old', action='read')
   do
   read(41,'(A)',iostat=ios) line
   if (ios /= 0) exit
   if (trim(line)=='' .or. line(1:1)=='#') cycle
   if (index(line,'LAT')>0 .and. index(line,'LON')>0) cycle

   read(line,'(A10,2X,F10.6,2X,F10.6,2X,F12.2,2X,F12.2)', iostat=ios)  &
        idx_token, lat, lon, ldaps_y, ldaps_x
   if (ios /= 0) cycle

   p1 = index(idx_token,'(')
   pc = index(idx_token,',')
   p2 = index(idx_token,')')
   if (p1==0 .or. pc==0 .or. p2==0) cycle

   read(idx_token(p1+1:pc-1),*,iostat=ios) x_idx
   if (ios /= 0) cycle
   read(idx_token(pc+1:p2-1),*,iostat=ios) y_idx
   if (ios /= 0) cycle

   if (x_idx == x_min .and. y_idx == y_min) then
!      print *, '==============================================='
!      print *, '[INFO] LDAPS lower-left index : ', x_min, y_min
!      print *, '[INFO] LDAPS TM_X, TM_Y       : ', ldaps_x, ldaps_y
!      print *, '==============================================='
      exit
   end if
   end do
   close(41)

   !-------------------------------------------------------------
   ! Compute automatic cutting indices
   !-------------------------------------------------------------
   ! Fortran arrays are 1-based. The coordinate offset is zero-based,
   ! so add 1 before slicing the interpolated RDAPS field.
   i_sta = nint((x_cfd_min - ldaps_x) / dx) + 1
   j_sta = nint((y_cfd_min - ldaps_y) / dy) + 1
   i_end = (ilmax - 1) + i_sta
   j_end = (jlmax - 1) + j_sta

   if (i_sta < 1 .or. j_sta < 1 .or. i_end > ifmax .or. j_end > jfmax) then
      print *, 'ERROR: CFD cut indices are outside interpolated RDAPS domain'
      print *, 'i_sta,i_end,ifmax = ', i_sta, i_end, ifmax
      print *, 'j_sta,j_end,jfmax = ', j_sta, j_end, jfmax
      stop
   end if

!   print *, '[INFO] Auto-cut domain indices (i_sta, j_sta):', i_sta, j_sta

   do k=1,kmax
      do j=j_sta, j_end
         do i=i_sta, i_end
            write(11,'(f12.6)') uu(i,j,k)
            write(12,'(f12.6)') vv(i,j,k)
            write(13,'(f12.6)') tt(i,j,k)
         end do
      end do
   end do
   close(11); close(12); close(13)

!   write(*,'(A,I4.4,".",I2.2,".",I2.2,".",I2.2)') 'Successfully stop ! ', yy, mm, dd, HH
!   print *, "== All input data preparing processes completed successfully! =="
end subroutine run_horizontal_interpolation
