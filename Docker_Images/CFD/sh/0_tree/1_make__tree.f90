program make_tree_input
  implicit none

  call process_height()
  call process_frtp()
  call process_dnst()

end program make_tree_input


subroutine read_info(infofile, ncols, nrows, xllcorner, yllcorner,cellsize, ulx, uly)
  implicit none

  character(len=*), intent(in)  :: infofile
  integer,          intent(out) :: ncols
  integer,          intent(out) :: nrows
  real,             intent(out) :: xllcorner
  real,             intent(out) :: yllcorner
  real,             intent(out) :: cellsize
  real,             intent(out) :: ulx
  real,             intent(out) :: uly

  integer :: ios
  character(len=100) :: line
  character(len=40)  :: keyword

  ncols     = 0
  nrows     = 0
  xllcorner = 0.0
  yllcorner = 0.0
  cellsize  = 0.0
  ulx       = 0.0
  uly       = 0.0

  open(unit=10, file=trim(infofile), status='old', action='read')

  do
    read(10,'(A)',iostat=ios) line
    if (ios /= 0) exit

    read(line,*) keyword

    select case (trim(keyword))
    case ('XLLCORNER')
      read(line,*) keyword, xllcorner
    case ('YLLCORNER')
      read(line,*) keyword, yllcorner
    case ('CELLSIZE')
      read(line,*) keyword, cellsize
    case ('NCOLS')
      read(line,*) keyword, ncols
    case ('NROWS')
      read(line,*) keyword, nrows
    case ('ULx')
      read(line,*) keyword, ulx
    case ('ULy')
      read(line,*) keyword, uly
    end select
  end do

  close(10)

end subroutine read_info


subroutine process_height()
  implicit none

  integer :: ncols, nrows
  real    :: xllcorner, yllcorner, cellsize, ulx, uly
  real, allocatable :: arr(:,:)

  integer :: i, j, ios
  real    :: dummy_val
  real    :: nodata_val
  character(len=40) :: key

  call read_info('./output_tree/HEIGHT_model_info.txt', &
                 ncols, nrows, xllcorner, yllcorner, cellsize, ulx, uly)

  allocate(arr(ncols, nrows))
  arr = 0.0

  open(unit=11, file='./output_tree/HEIGHT_model.asc', status='old',action='read')
  open(unit=31, file='./cut/tree_height_model.txt', status='replace',action='write')

  read(11,*) key, i
  read(11,*) key, j
  read(11,*) key, dummy_val
  read(11,*) key, dummy_val
  read(11,*) key, dummy_val
  read(11,*) key, nodata_val

  do j = 1, nrows
    read(11,*,iostat=ios) (arr(i,j), i=1,ncols)
    if (ios /= 0) then
      print *, 'Error reading HEIGHT row = ', j
      stop
    end if
  end do

  close(11)

  do i = 1, ncols
    do j = 1, nrows
      if (arr(i,j) == nodata_val) then
        arr(i,j) = 0.0
      else if (arr(i,j) < 0.0) then
        arr(i,j) = 0.0
      end if
    end do
  end do

  do j = 1, nrows
    write(31,'(*(F10.2))') (arr(i,j), i=1,ncols)
  end do

  close(31)
  deallocate(arr)

!  print *, '[OK] HEIGHT processed'

end subroutine process_height


subroutine process_frtp()
  implicit none

  integer :: ncols, nrows
  real    :: xllcorner, yllcorner, cellsize, ulx, uly
  real, allocatable :: arr(:,:)

  integer :: i, j, ios
  real    :: dummy_val
  real    :: nodata_val
  character(len=40) :: key

  call read_info('./output_tree/FRTP_CD_model_info.txt', &
                 ncols, nrows, xllcorner, yllcorner, cellsize, ulx, uly)

  allocate(arr(ncols, nrows))
  arr = 0.0

  open(unit=12, file='./output_tree/FRTP_CD_model.asc', status='old',action='read')
  open(unit=32, file='./cut/tree_frtp_cd_model.txt', status='replace',action='write')

  read(12,*) key, i
  read(12,*) key, j
  read(12,*) key, dummy_val
  read(12,*) key, dummy_val
  read(12,*) key, dummy_val
  read(12,*) key, nodata_val

  do j = 1, nrows
    read(12,*,iostat=ios) (arr(i,j), i=1,ncols)
    if (ios /= 0) then
      print *, 'Error reading FRTP_CD row = ', j
      stop
    end if
  end do

  close(12)

  do i = 1, ncols
    do j = 1, nrows
      if (arr(i,j) == nodata_val) then
        arr(i,j) = 0.0
      else
        arr(i,j) = real(nint(arr(i,j)))
      end if
    end do
  end do

  do j = 1, nrows
    write(32,'(*(I10))') (nint(arr(i,j)), i=1,ncols)
  end do

  close(32)
  deallocate(arr)

!  print *, '[OK] FRTP_CD processed'

end subroutine process_frtp


subroutine process_dnst()
  implicit none

  integer :: ncols, nrows
  real    :: xllcorner, yllcorner, cellsize, ulx, uly
  real, allocatable :: arr(:,:)

  integer :: i, j, ios
  real    :: dummy_val
  real    :: nodata_val
  character(len=40) :: key

  call read_info('./output_tree/DNST_CD_model_info.txt', &
                 ncols, nrows, xllcorner, yllcorner, cellsize, ulx, uly)

  allocate(arr(ncols, nrows))
  arr = 0.0

  open(unit=13, file='./output_tree/DNST_CD_model.asc', status='old',action='read')
  open(unit=33, file='./cut/tree_dnst_cd_model.txt', status='replace',action='write')

  read(13,*) key, i
  read(13,*) key, j
  read(13,*) key, dummy_val
  read(13,*) key, dummy_val
  read(13,*) key, dummy_val
  read(13,*) key, nodata_val

  do j = 1, nrows
    read(13,*,iostat=ios) (arr(i,j), i=1,ncols)
    if (ios /= 0) then
      print *, 'Error reading DNST_CD row = ', j
      stop
    end if
  end do

  close(13)

  do i = 1, ncols
    do j = 1, nrows
      if (arr(i,j) == nodata_val) then
        arr(i,j) = 0.0
      else
        arr(i,j) = real(nint(arr(i,j)))
      end if
    end do
  end do

  do j = 1, nrows
    write(33,'(*(I10))') (nint(arr(i,j)), i=1,ncols)
  end do

  close(33)
  deallocate(arr)

!  print *, '[OK] DNST_CD processed'

end subroutine process_dnst
