        program Emission_rate
        IMPLICIT NONE
        integer :: imax, jmax
        integer :: imax2, jmax2
        integer :: ntime
        integer :: fire_ncols, fire_nrows, fire_ntime, fire_kmax
        real :: fire_cellsize, fire_vertical_resolution
          
        real, allocatable :: lc_ratio(:,:,:)
        real, allocatable :: fireline(:,:,:), ER(:,:,:)
        real, allocatable :: area(:)
        integer, allocatable :: seconds(:)
        integer :: i, j, k, c
        integer :: dt_seconds
        real :: sum_H, sum_D, contrib
        real,dimension(4) :: rate, classrate
        real,dimension(4) :: H, D
        character(len=120) :: ratiofile
        character(len=240) :: header_line

       call read_grid_size('./output_landcover/LC_CLASS_model_info.txt', &
     &                      imax2, jmax2)
        imax = imax2 - 2
        jmax = jmax2 - 2

        call read_fireline_info( &
     &'../0_fireline/result_fireline/fire_intensity_timeseries_info.txt',&
     & fire_ncols, fire_nrows, fire_cellsize, fire_vertical_resolution, &
     & fire_kmax, fire_ntime)

        if (fire_ncols .ne. imax2 .or. fire_nrows .ne. jmax2) then
          print *, 'Fireline grid does not match landcover grid.'
          print *, 'fireline=', fire_ncols, fire_nrows, &
     &             ' landcover=', imax2, jmax2
          stop
        end if

        allocate(lc_ratio(imax2,jmax2,4))
        
        lc_ratio(:,:,:) = 0.

        do c=1,4
          write(ratiofile,'(A,I1,A)') './cut/landcover_lc_class_ratio_', &
     &                                c, '.txt'
          open(10+c, file=trim(ratiofile), status='old', action='read')
          read(10+c,*) ((lc_ratio(i,j,c),i=1,imax2),j=1,jmax2)
          close(10+c)
        end do

        open(11,file='../0_fireline/result_fireline/fire_intensity_time&
     &series.txt') 
        open(12, file='./emis_result/emission_rate.txt')

        call count_fireline_blocks(11, jmax2, ntime)
        if (fire_ntime .ne. ntime) then
          print *, 'Fireline NTIME does not match timeseries blocks.'
          print *, 'info=', fire_ntime, ' blocks=', ntime
          stop
        end if
        rewind(11)

        allocate(fireline(imax2,jmax2,ntime))
        allocate(ER(imax2,jmax2,ntime))
        allocate(area(0:ntime))
        allocate(seconds(ntime))

        fireline(:,:,:) = 0.
        ER(:,:,:) = 0.
        area(:) = 0.

        do 100 k=1,ntime
        read(11,'(A)') header_line
        call parse_fireline_header(header_line, seconds(k), area(k))
  100   read(11,*) ((fireline(i,j,k),i=1,imax2),j=1,jmax2)

        do 110 k=1, ntime
           if (k == 1) then
             if (ntime < 2) then
               stop
             end if
             dt_seconds = seconds(2) - seconds(1)
           else
             dt_seconds = seconds(k) - seconds(k-1)
           end if

           if (dt_seconds <= 0) then
             print *, 'Invalid fireline time interval at block ', k
             stop
           end if

!           rate(1) = 4639.89/real(dt_seconds)*1000.
!           rate(2) = 68782.50/real(dt_seconds)*1000.
!           rate(3) = 82080.45/real(dt_seconds)*1000.
!           rate(4) = 4355.755/real(dt_seconds)*1000.

           rate(1) = 4639888/real(dt_seconds)
           rate(2) = 53088750/real(dt_seconds)
           rate(3) = 63352575/real(dt_seconds)
           rate(4) = 4659066/real(dt_seconds)

           H(:) = 0
           D(:) = 0
           classrate(1)=rate(1)*(area(k)-area(k-1))
           classrate(2)=rate(2)*(area(k)-area(k-1))
           classrate(3)=rate(3)*(area(k)-area(k-1))
           classrate(4)=rate(4)*(area(k)-area(k-1))    !------------(1)
         
        do 120 j=1, jmax2
        do 120 i=1, imax2

          if (fireline(i,j,k).ge.0.1) then
            do c=1,4
              H(c) = H(c)+lc_ratio(i,j,c)
            end do
          else if (fireline(i,j,k).le.-0.1) then
            do c=1,4
              D(c) = D(c)+lc_ratio(i,j,c)
            end do
         end if
  120   continue                             !---------------(2)

         SUM_H = H(1)+H(2)+H(3)+H(4)  
         SUM_D = D(1)+D(2)+D(3)+D(4)  

         if (SUM_H+SUM_D .gt. 0.0) then
           do c=1,4
             classrate(c) = classrate(c)*(H(c)+D(c))/(SUM_H+SUM_D)
           end do
         else
           classrate(:) = 0.0
         end if                                      !--------------(3)
 
        do 130 j=1, jmax2
        do 130 i=1, imax2

            if (fireline(i,j,k).ge.0.1) then
              do c=1,4
                if (lc_ratio(i,j,c).gt.0.0 .and. H(c).gt.0.0) then
                  if (D(c).gt.0.0) then
                    contrib = classrate(c)/2.0/H(c)
                  else
                    contrib = classrate(c)/H(c)
                  end if
                  ER(i,j,k) = ER(i,j,k)+lc_ratio(i,j,c)*contrib
                end if
              end do

            elseif (fireline(i,j,k).le.-0.1) then
              do c=1,4
                if (lc_ratio(i,j,c).gt.0.0 .and. D(c).gt.0.0) then
                  if (H(c).gt.0.0) then
                    contrib = classrate(c)/2.0/D(c)
                  else
                    contrib = classrate(c)/D(c)
                  end if
                  ER(i,j,k) = ER(i,j,k)+lc_ratio(i,j,c)*contrib
                end if
              end do
            end if

        130 continue                                  !--------------------(4)

  110   continue

       do k=1,ntime
        write(12,'(A2,I4.4)') 'T=', seconds(k)
        write(12,140) ((ER(i,j,k),i=1,imax2),j=1,jmax2)
       end do

  140  FORMAT(*(ES15.6,1x))

        deallocate(lc_ratio)
        deallocate(fireline)
        deallocate(ER)
        deallocate(area)
        deallocate(seconds)

        end program

        subroutine count_fireline_blocks(unit_no, jmax2, ntime)
        implicit none

        integer, intent(in) :: unit_no, jmax2
        integer, intent(out) :: ntime

        integer :: ios, j
        character(len=240) :: line

        ntime = 0

        do
          read(unit_no,'(A)',iostat=ios) line
          if (ios /= 0) exit
          if (len_trim(line) == 0) cycle

          ntime = ntime + 1
          do j=1,jmax2
            read(unit_no,'(A)',iostat=ios) line
            if (ios /= 0) then
              print *, 'Unexpected end of fireline timeseries.'
              stop
            end if
          end do
        end do

        if (ntime <= 0) then
          print *, 'No fireline blocks found.'
          stop
        end if

        end subroutine count_fireline_blocks

        subroutine parse_fireline_header(line, seconds, area)
        implicit none

        character(len=*), intent(in) :: line
        integer, intent(out) :: seconds
        real, intent(out) :: area

        integer :: comma_pos1, comma_pos2, area_pos, ios

        comma_pos1 = index(line, ',')
        comma_pos2 = comma_pos1 + index(line(comma_pos1+1:), ',')
        area_pos = index(line, 'A=')

        if (comma_pos1 <= 1 .or. comma_pos2 <= comma_pos1 .or. &
     &      area_pos <= 0) then
          print *, 'Invalid fireline header: ', trim(line)
          stop
        end if

        read(line(comma_pos1+1:comma_pos2-1),*,iostat=ios) seconds
        if (ios /= 0) then
          print *, 'Invalid fireline time: ', trim(line)
          stop
        end if

        read(line(area_pos+2:),*,iostat=ios) area
        if (ios /= 0) then
          print *, 'Invalid fireline area: ', trim(line)
          stop
        end if

        end subroutine parse_fireline_header

        subroutine read_fireline_info(infofile, ncols, nrows, cellsize, &
     &                                vertical_resolution, kmax, ntime)
        implicit none

        character(len=*), intent(in) :: infofile
        integer, intent(out) :: ncols, nrows, kmax, ntime
        real, intent(out) :: cellsize, vertical_resolution

        integer :: ios
        character(len=140) :: line
        character(len=40) :: keyword

        ncols = 0
        nrows = 0
        kmax = 0
        ntime = 0
        cellsize = 0.0
        vertical_resolution = 0.0

        open(unit=21, file=trim(infofile), status='old', action='read', &
     &       iostat=ios)
        if (ios /= 0) then
          print *, 'Cannot open fireline info: ', trim(infofile)
          stop
        end if

        do
          read(21,'(A)',iostat=ios) line
          if (ios /= 0) exit
          if (len_trim(line) == 0) cycle

          read(line,*) keyword

          select case (trim(keyword))
          case ('NCOLS')
            read(line,*) keyword, ncols
          case ('NROWS')
            read(line,*) keyword, nrows
          case ('CELLSIZE')
            read(line,*) keyword, cellsize
          case ('VERTICAL_RESOLUTION_M')
            read(line,*) keyword, vertical_resolution
          case ('KMAX')
            read(line,*) keyword, kmax
          case ('NTIME')
            read(line,*) keyword, ntime
          end select
        end do

        close(21)

        if (ncols <= 0 .or. nrows <= 0 .or. cellsize <= 0.0 .or. &
     &      vertical_resolution <= 0.0 .or. kmax <= 0 .or. &
     &      ntime <= 0) then
          print *, 'Invalid fireline info: ', trim(infofile)
          stop
        end if

        end subroutine read_fireline_info

        subroutine read_grid_size(infofile, imax2, jmax2)
        implicit none

        character(len=*), intent(in) :: infofile
        integer, intent(out) :: imax2, jmax2

        integer :: ios
        character(len=100) :: line
        character(len=40) :: keyword

        imax2 = 0
        jmax2 = 0

        open(unit=20, file=trim(infofile), status='old', action='read')

        do
          read(20,'(A)',iostat=ios) line
          if (ios /= 0) exit

          read(line,*) keyword

          select case (trim(keyword))
          case ('NCOLS')
            read(line,*) keyword, imax2
          case ('NROWS')
            read(line,*) keyword, jmax2
          end select
        end do

        close(20)

        imax2 = imax2 - 2
        jmax2 = jmax2 - 2

        if (imax2 <= 0 .or. jmax2 <= 0) then
          print *, 'Invalid grid size in ', trim(infofile)
          stop
        end if

        end subroutine read_grid_size
