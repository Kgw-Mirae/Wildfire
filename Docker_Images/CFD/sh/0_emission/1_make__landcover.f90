program make_landcover_input
  implicit none

  call process_lc_class()
  call process_lc_ratio()

end program make_landcover_input


subroutine read_info(infofile, ncols, nrows, xllcorner, yllcorner, cellsize, ulx, uly)
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


subroutine process_lc_class()
  implicit none

  integer :: ncols, nrows
  real    :: xllcorner, yllcorner, cellsize, ulx, uly
  integer, allocatable :: arr(:,:)

  integer :: i, j, ios
  real    :: dummy_val
  real    :: nodata_val
  character(len=40) :: key

  call read_info('./output_landcover/LC_CLASS_model_info.txt', &
                 ncols, nrows, xllcorner, yllcorner, cellsize, ulx, uly)

  allocate(arr(ncols, nrows))
  arr = 0

  open(unit=11, file='./output_landcover/LC_CLASS_model.asc', status='old', action='read')
  open(unit=31, file='./cut/landcover_lc_class_model.txt', status='replace', action='write')

  read(11,*) key, i
  read(11,*) key, j
  read(11,*) key, dummy_val
  read(11,*) key, dummy_val
  read(11,*) key, dummy_val
  read(11,*) key, nodata_val

  do j = 1, nrows
    read(11,*,iostat=ios) (arr(i,j), i=1,ncols)
    if (ios /= 0) then
      print *, 'Error reading LC_CLASS row = ', j
      stop
    end if
  end do

  close(11)

  do i = 1, ncols
    do j = 1, nrows
      if (real(arr(i,j)) == nodata_val) then
        arr(i,j) = 0
      else if (arr(i,j) < 0) then
        arr(i,j) = 0
      end if
    end do
  end do

!  do j = 1, nrows
!    write(31,'(*(I3))') (arr(i,j), i=1,ncols)
!  end do

  do j = 2, nrows - 1
    write(31,'(*(I3))') (arr(i,j), i=2,ncols - 1)
  end do

  close(31)
  deallocate(arr)

end subroutine process_lc_class


subroutine process_lc_ratio()
  implicit none

  integer :: ncols, nrows
  real    :: xllcorner, yllcorner, cellsize, ulx, uly
  real, allocatable :: arr(:,:)

  integer :: i, j, k, ios
  real    :: dummy_val
  real    :: nodata_val
  character(len=40) :: key
  character(len=120) :: infile, outfile

  call read_info('./output_landcover/LC_CLASS_model_info.txt', &
                 ncols, nrows, xllcorner, yllcorner, cellsize, ulx, uly)

  allocate(arr(ncols, nrows))

  do k = 1, 4
    write(infile,'(A,I1,A)') './output_landcover/LC_CLASS_RATIO_', k, '_model.asc'
    write(outfile,'(A,I1,A)') './cut/landcover_lc_class_ratio_', k, '.txt'

    arr = 0.0

    open(unit=11, file=trim(infile), status='old', action='read')
    open(unit=31, file=trim(outfile), status='replace', action='write')

    read(11,*) key, i
    read(11,*) key, j
    read(11,*) key, dummy_val
    read(11,*) key, dummy_val
    read(11,*) key, dummy_val
    read(11,*) key, nodata_val

    do j = 1, nrows
      read(11,*,iostat=ios) (arr(i,j), i=1,ncols)
      if (ios /= 0) then
        print *, 'Error reading LC_CLASS_RATIO row = ', j, ', class = ', k
        stop
      end if
    end do

    close(11)

    do i = 1, ncols
      do j = 1, nrows
        if (arr(i,j) == nodata_val .or. arr(i,j) < 0.0) then
          arr(i,j) = 0.0
        end if
      end do
    end do

    do j = 2, nrows - 1
      write(31,'(*(F12.8,1X))') (arr(i,j), i=2,ncols - 1)
    end do

    close(31)
  end do

  deallocate(arr)

end subroutine process_lc_ratio
