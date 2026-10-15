      PROGRAM make_topography

      IMPLICIT NONE

      CALL CUT
      CALL TOP

      END PROGRAM make_topography 


!====================================================================
      SUBROUTINE CUT
!====================================================================
       IMPLICIT NONE
!cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
!cccccccccccccccccccccccccc THE NUMBER OF TOTAL DOMAIN cccccccccccccccccccccccc
!cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc

! The number of the total domain (contour and building) 
! c_col = the number of total column for contour
! c_row = the number of total row for contour
! new_col = the number of the final domain in the x-direction
! new_row = the number of the final domain in the y-direction

! info.txt
      real :: XLLCORNER, YLLCORNER, CELLSIZE, ULx, ULy
      integer :: NCOLS, NROWS
      integer :: ios
      character(len=200) :: line, keyword

! domain
      integer :: c_col, c_row
      integer :: new_col, new_row
      real    :: c_xllcorner, c_yllcorner
      real    :: r
      integer :: cx_cut, cy_cut

      real, allocatable :: con_floor(:,:), con_heigt(:,:)
      real, allocatable :: c_topo(:,:), contour(:,:)

! etc
      REAL              :: x1,y1,hmin
      INTEGER           :: i,j,k
      character         :: gun,gu

      character(len=64) :: fmt_top_i1
      character(len=64) :: fmt_top_f42

!================= read info.txt ========
      open(unit=10, file="./output/output_topo_source_info.txt", status="old", action="read") ! HJ
    
      do
      read(10,'(A)',iostat=ios) line
      if (ios /= 0) exit

      read(line,*) keyword
      select case (trim(keyword))
      case ("XLLCORNER")
         read(line,*) keyword, XLLCORNER
      case ("YLLCORNER")
         read(line,*) keyword, YLLCORNER
      case ("CELLSIZE")
         read(line,*) keyword, CELLSIZE
      case ("NCOLS")
         read(line,*) keyword, NCOLS
      case ("NROWS")
         read(line,*) keyword, NROWS
      case ("ULx")
         read(line,*) keyword, ULx
      case ("ULy")
         read(line,*) keyword, ULy
      end select
      end do

      close(10)

!      print *, "XLLCORNER=", XLLCORNER
!      print *, "YLLCORNER=", YLLCORNER
!      print *, "CELLSIZE =", CELLSIZE
!      print *, "NCOLS   =", NCOLS
!      print *, "NROWS   =", NROWS
!      print *, "ULx     =", ULx
!      print *, "ULy     =", ULy

      c_col = NCOLS
      c_row = NROWS
      new_col = NCOLS
      new_row = NROWS
      r = CELLSIZE
      c_xllcorner = XLLCORNER
      c_yllcorner = YLLCORNER 

! ********************

! To cut domain (contour and building)  
! cx_cut = the starting point to cut the contour_domain in the x-direction
! cy_cut = the starting point to cut the contour_domain in the y-direction
 
      cx_cut= nint(abs((c_xllcorner-ULx)/r))
      cy_cut= nint(abs((c_yllcorner+(c_row*r)-ULy)/r))

      allocate(con_floor(c_col,c_row))
      allocate(con_heigt(c_col,c_row))
      allocate(c_topo(c_col,c_row))
      allocate(contour(new_col,new_row))
 
!cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
!cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc

 
!##### input file - raw data (building and contour)

      OPEN(10,FILE='./output/output_topo_source.asc') !HJ

!##### output file - cut domain (building and contour) 

      OPEN(30,FILE="./cut/cut_auto_10m.txt")  !HJ

 1111 FORMAT(*(F10.2)) 

!########## Part for reading and preprocessing a raw data ##########

      DO  i=1,c_col
      DO  j=1,c_row
      con_floor(i,j)=0.
      con_heigt(i,j)=0.
      ENDDO
      ENDDO

      READ(10,210) 
      READ(10,211) 
      READ(10,*)  gun, x1 
      READ(10,*)  gun, y1
      READ(10,214) 
      READ(10,215) 

  210 FORMAT(a14,i5)
  211 FORMAT(a14,i5)
  214 FORMAT(a14,i5)
  215 FORMAT(a14,i5)

!########### read topo #############

      DO j=1,c_row
      READ(10,*) (con_floor(i,j),i=1,c_col)
      ENDDO

      DO i=1,c_col
      DO j=1,c_row
       IF (con_floor(i,j) .le. 0) THEN 
            con_heigt(i,j)=0
        ELSE
            con_heigt(i,j)=con_floor(i,j)
        ENDIF

      ENDDO
      ENDDO

!############ change value ##########

      DO i = 1, c_col
       DO j = 1, c_row
        c_topo(i,j)=con_heigt(i,j)
       ENDDO
      ENDDO

!############ cut domain ##########

      DO i = 1, new_col
       DO j = 1, new_row
        contour(i,j) = c_topo(cx_cut+i, cy_cut+j)
       ENDDO
      ENDDO

!############  base height ##########

      hmin= 9999999.

      DO i = 2, new_col-1
       DO j = 2, new_row-1
         
        if(contour(i,j) .lt. hmin) then
        hmin=contour(i,j)
        endif
       ENDDO
      ENDDO

      print*, 'BASE_HEIGHT_M', hmin

      open(unit=90, file="./output/output_model_info.txt", &
     &     status="old", action="write", position="append", iostat=ios)
      if (ios == 0) then
       write(90,'(A,1X,F12.6)') 'BASE_HEIGHT_M', hmin
       close(90)
      else
       print*, 'WARN: Cannot append BASE_HEIGHT_M to output_model_info.txt'
      endif

      DO i = 1, new_col
       DO j = 1, new_row
        contour(i,j)=contour(i,j)-hmin 

       if(contour(i,j) > 0 )then
        contour(i,j) = contour(i,j)
       else
        contour(i,j) = 0
       endif
       ENDDO
      ENDDO

!##### output file - cut domain (building and contour)

      DO j = 1, new_row
       WRITE(30,1111) (contour(i,j), i=1,new_col)
      ENDDO

      END SUBROUTINE CUT

!====================================================================
      SUBROUTINE TOP
!====================================================================
      
       IMPLICIT NONE
!cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
!ccccccccccccccccccccccccccc INTERPOLATION CONTOUR
!cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
        include '../data/Domain/topo_domain.inc'
        REAL,PARAMETER :: cut_min=0.3, cut_max=0.7                !cut-cell range 30%~70%


        INTEGER,PARAMETER :: nx=new_col/(out_col-4)
        INTEGER,PARAMETER :: ny=new_row/(out_row-4)
        INTEGER,PARAMETER :: in_col=new_col,in_row=new_row
        REAL,PARAMETER :: c_col=in_col/out_col, c_row=in_row/out_row
        REAL,PARAMETER :: cnum=c_col*c_row

        REAL,DIMENSION(out_col+1,out_row+1,out_kmax+1):: afaa,afab,afac
        REAL,DIMENSION(out_col+1,out_row+1,out_kmax+1):: afav
        REAL,DIMENSION(out_col+1,out_row+1,out_kmax+1):: afba,afbb,afbc
        REAL,DIMENSION(out_col+1,out_row+1,out_kmax+1):: afbv
        REAL,DIMENSION(out_col+1,out_row+1,out_kmax+1):: afca,afcb,afcc
        REAL,DIMENSION(out_col+1,out_row+1,out_kmax+1):: afcv
        REAL,DIMENSION(out_col+1,out_row+1,out_kmax+1):: afsa,afsb,afsc
        REAL,DIMENSION(out_col+1,out_row+1,out_kmax+1):: afsv
        INTEGER,DIMENSION(out_col,out_row,out_kmax) :: cutcell
        INTEGER,DIMENSION(out_col,out_row,out_kmax) :: ucutcell,vcutcell


        REAL,DIMENSION(in_col,in_row) :: itopo
        REAL,DIMENSION(in_col,in_row) :: iitopo

        INTEGER :: i,j,k,m,n,l,t
        REAL :: frac

        !OPEN(20,FILE="./cut/cut_auto_10m.txt")
        !OPEN(70,FILE='./top/cut_auto.top' ,status='unknown')
        !OPEN(80,FILE='./top/fraction_coefficient.txt' ,status='unknown')
        OPEN(20,FILE='./cut/cut_auto_10m.txt', &
     &       STATUS='OLD', ACTION='READ')
        OPEN(70,FILE='./top/cut_auto.top', &
     &       STATUS='REPLACE', ACTION='WRITE')
        OPEN(80,FILE='./top/fraction_coefficient.txt', &
     &       STATUS='REPLACE', ACTION='WRITE')

        iitopo = 0.0
        itopo  = 0.0

        afaa = 1.0 ; afab = 1.0 ; afac = 1.0 ; afav = 1.0
        afba = 1.0 ; afbb = 1.0 ; afbc = 1.0 ; afbv = 1.0
        afca = 1.0 ; afcb = 1.0 ; afcc = 1.0 ; afcv = 1.0
        afsa = 1.0 ; afsb = 1.0 ; afsc = 1.0 ; afsv = 1.0

        cutcell  = 0
        ucutcell = 0
        vcutcell = 0
        print*,'HJ'
        DO j = 1, in_row
         read(20,*) (iitopo(i,j), i=1,in_col)
        ENDDO
        itopo(:,:)=iitopo(:,:)
!cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
!   MAKE CUT-CELL .top FILE 

        !Volume-S
        Do k=1,out_kmax
         Do i=1,out_col
          Do j=1,out_row
           frac=0.0
           Do m=(i-1)*c_col+1,i*c_col
           Do n=(j-1)*c_row+1,j*c_row
             IF(itopo(m,n).le.odz) then
              frac=frac+itopo(m,n)
             ELSE
              frac=frac+odz
             end if
                If (k.ge.2) then
                  itopo(m,n)=itopo(m,n)-odz
                   If (itopo(m,n).le.0.)then
                    itopo(m,n)=0.
                   End if
                End if
              End do      !m
           End do      !n
           afsv(i,j,k)=(frac*idx*idy)/(odz*odx*ody)

           If (k.eq.1) afsv(i,j,k)=1.
          End do       !j
         End do        !i
        Enddo          !k


        !S
        Do k=1,out_kmax
         Do i=1,out_col
          Do j=1,out_row
          If (afsv(i,j,k).gt.cut_min .and. afsv(i,j,k).lt.cut_max) then
            cutcell(i,j,k)=2
          Else if ( afsv(i,j,k).ge.cut_max ) then                   !
            cutcell(i,j,k)=0
            afsv(i,j,k)=1.
          Else
            cutcell(i,j,k)=1
            afsv(i,j,k)=0.
          End if

        IF (k.eq.1) cutcell(i,j,k) = 0
          End do     !j
         End do      !i
        End do       !k

        !U
        Do k=1,out_kmax
         Do i=1,out_col
          Do j=1,out_row
           If (cutcell(i,j,k).ne.0 .and. cutcell(i+1,j,k).eq.0) then
               ucutcell(i,j,k) = 0
           Else
               ucutcell(i,j,k) = cutcell(i,j,k)
           End if
          End do     !j
         End do      !i
        End do       !k

        !V
        Do k=1,out_kmax
         Do i=1,out_col
          Do j=1,out_row
           If (cutcell(i,j,k).ne.0 .and. cutcell(i,j-1,k).eq.0) then
               vcutcell(i,j,k) = 0
           Else
               vcutcell(i,j,k) = cutcell(i,j,k)
           End if
          End do     !j
         End do      !i
        End do
        !Volume-U
        Do k=1,out_kmax
         Do i=1,out_col
          Do j=1,out_row
            afav(i,j,k)=(afsv(i,j,k)+afsv(i+1,j,k))/2.
           IF(afav(i,j,k).ge.cut_max) afav(i,j,k)=1.
           IF(afav(i,j,k).le.cut_min) afav(i,j,k)=0.
          End do       !j
         End do        !i
        Enddo          !k

        !Volume-V
        Do k=1,out_kmax
         Do i=1,out_col
          Do j=1,out_row
           afbv(i,j,k)=(afsv(i,j,k)+afsv(i,j-1,k))/2.
           IF(afbv(i,j,k).ge.cut_max) afbv(i,j,k)=1.
           IF(afbv(i,j,k).le.cut_min) afbv(i,j,k)=0.
           End do       !j
          End do        !i
         Enddo          !k

        !Volume-W
        Do k=1,out_kmax
         Do i=1,out_col
          Do j=1,out_row
           afcv(i,j,k)=(afsv(i,j,k)+afsv(i,j,k+1))/2.
           IF(afcv(i,j,k).ge.cut_max) afcv(i,j,k)=1.
           IF(afcv(i,j,k).le.cut_min) afcv(i,j,k)=0.
          End do       !j
         End do        !i
        Enddo          !k
!cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
!   PRINT CUT-CELL.top FILE

3333    FORMAT (*(I1))
2222    FORMAT (*((1x,f4.2)))
222     FORMAT(A4,I3)

!cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc

!   CALCULATE AREA FRACTION COEFFICIENT FILE


!  1.Scalar
        !U
        itopo(:,:)=iitopo(:,:)

        Do k=1,out_kmax
         Do i=1,out_col
          Do j=1,out_row
           frac=0.0

           Do n=(j-1)*c_row+1,j*c_row
              m=(i-1)*c_col+1
              IF (itopo(m,n).le.odz) then
               frac=frac+itopo(m,n)
              else
               frac=frac+odz
              End if

              if (k.ge.2) then
               itopo(m,n)=itopo(m,n)-odz
               If (itopo(m,n).le.0.)then
                itopo(m,n)=0.0
               End IF
              end if

           End do      !n
           afsa(i,j,k)=(frac*idy)/(odz*ody)

           if(i.ge.2) then
             Do n=(j-1)*c_row+1,j*c_row
              m=(i-1)*c_col
              IF (itopo(m,n).le.odz) then
               frac=frac+itopo(m,n)
              else
               frac=frac+odz
              End if

              if (k.ge.2) then
               itopo(m,n)=itopo(m,n)-odz
               If (itopo(m,n).le.0.)then
                itopo(m,n)=0.0
               End IF
              end if

           End do      !n
           afsa(i,j,k)=(frac*idy)/(2*odz*ody)
           End if
            If (k.eq.1) afsa(i,j,k)=1.
          End do       !j
         End do        !i
        End do         !k

        !V
        itopo(:,:)=iitopo(:,:)

        Do k=1,out_kmax
         Do i=1,out_col
          Do j=1,out_row
           frac=0.0
           Do m=(i-1)*c_col+1,i*c_col
              n=(j-1)*c_row+1
             IF(itopo(m,n).le.odz) then
              frac=frac+itopo(m,n)
             ELSE
              frac=frac+odz
             end if
                If (k.ge.2) then
                  itopo(m,n)=itopo(m,n)-odz
                   If (itopo(m,n).le.0.)then
                    itopo(m,n)=0.
                   End if
                End if
           End do      !m
           afsb(i,j,k)=(frac*idx)/(odz*odx)

           if (j.ge.2) then
           Do m=(i-1)*c_col+1,i*c_col
              n=(j-1)*c_row
             IF(itopo(m,n).le.odz) then
              frac=frac+itopo(m,n)
             ELSE
              frac=frac+odz
             end if
                If (k.ge.2) then
                  itopo(m,n)=itopo(m,n)-odz
                   If (itopo(m,n).le.0.)then
                    itopo(m,n)=0.
                   End if
                End if
           End do      !m
           afsb(i,j,k)=(frac*idx)/(2*odz*odx)
           ENd if
           If (k.eq.1) afsb(i,j,k)=1.
          End do       !j
         End do        !i
        Enddo          !k

        !W
        itopo(:,:)=iitopo(:,:)
        Do k=1,out_kmax
         Do i=1,out_col
          Do j=1,out_row
           frac=0.0
           Do m=(i-1)*c_col+1,i*c_col
            Do n=(j-1)*c_row+1,j*c_row
              IF(itopo(m,n).ge.odz)then
               frac=frac+1.
              End IF
              If (k.ge.3) then
                itopo(m,n)=itopo(m,n)-odz
                IF (itopo(m,n).lt.0.)then
                 itopo(m,n)=0.
                End if
              end if
            End do   !n
           End do    !m
            afsc(i,j,k)=(frac*idx*idy)/(odx*ody)
           If (k.eq.1 .or. k.eq.2) afsc(i,j,k)=1.
         End do      !j
        End do       !i
       End do        !k 
!  2.UU - afa*

        !U
        itopo(:,:)=iitopo(:,:)
        Do k=1,out_kmax
         Do i=1,out_col-1
          Do j=1,out_row
           frac=0.0
           Do n=(j-1)*c_row+1,j*c_row
              m=(i-1)*c_col+1+(c_col/2.)
              IF (itopo(m,n).le.odz) then
               frac=frac+itopo(m,n)
              else
               frac=frac+odz
              End if
              if (k.ge.2) then
               itopo(m,n)=itopo(m,n)-odz
               If (itopo(m,n).le.0.)then
                itopo(m,n)=0.0
               End IF
              end if
           End do      !n
             Do n=(j-1)*c_row+1,j*c_row
              m=(i-1)*c_col+(c_col/2.)
              IF (itopo(m,n).le.odz) then
               frac=frac+itopo(m,n)
              else
               frac=frac+odz
              End if
              if (k.ge.2) then
               itopo(m,n)=itopo(m,n)-odz
               If (itopo(m,n).le.0.)then
                itopo(m,n)=0.0
               End IF
              end if
           End do      !n
           afaa(i,j,k)=(frac*idy)/(2*odz*ody)
            If (k.eq.1) afaa(i,j,k)=1.
          End do       !j
         End do        !i
        End do         !k
        !V
        itopo(:,:)=iitopo(:,:)
        Do k=1,out_kmax
         Do i=1,out_col-1
          Do j=1,out_row
           frac=0.0
           Do m=(i-1)*c_col+(c_col/2.)+1,i*c_col+(c_col/2.)
              n=(j-1)*c_row+1
             IF(itopo(m,n).le.odz) then
              frac=frac+itopo(m,n)
             ELSE
              frac=frac+odz
             end if
                If (k.ge.2) then
                  itopo(m,n)=itopo(m,n)-odz
                   If (itopo(m,n).le.0.)then
                    itopo(m,n)=0.
                   End if
                End if
           End do      !m
           Do m=(i-1)*c_col+(c_col/2.)+1,i*c_col+(c_col/2.)
              n=(j-1)*c_row
             IF(itopo(m,n).le.odz) then
              frac=frac+itopo(m,n)
             ELSE
              frac=frac+odz
             end if
                If (k.ge.2) then
                  itopo(m,n)=itopo(m,n)-odz
                   If (itopo(m,n).le.0.)then
                    itopo(m,n)=0.
                   End if
                End if
           End do      !m
           afab(i,j,k)=(frac*idx)/(2*odz*odx)
           If (k.eq.1) afab(i,j,k)=1.
          End do       !j
         End do        !i
        Enddo          !k
        !W
        itopo(:,:)=iitopo(:,:)
        Do k=1,out_kmax
         Do i=1,out_col-1
          Do j=1,out_row
           frac=0.0
           Do m=(i-1)*c_col+(c_col/2.)+1,i*c_col+(c_col/2.)
            Do n=(j-1)*c_row+1,j*c_row
              IF(itopo(m,n).ge.odz)then
               frac=frac+1.
              End IF
              If (k.ge.3) then
                itopo(m,n)=itopo(m,n)-odz
                IF (itopo(m,n).lt.0.)then
                 itopo(m,n)=0.
                End if
              end if
            End do   !n
           End do    !m
            afac(i,j,k)=(frac*idx*idy)/(odx*ody)
           If (k.eq.1 .or. k.eq.2) afac(i,j,k)=1.
         End do      !j
        End do       !i
       End do        !k 
!  3.VV - afb*
        !U
        itopo(:,:)=iitopo(:,:)
        Do k=1,out_kmax
         Do i=1,out_col
          Do j=2,out_row
           frac=0.0
           Do n=(j-1)*c_row+1-(c_row/2.),j*c_row-(c_row/2.)
              m=(i-1)*c_col+1
              IF (itopo(m,n).le.odz) then
               frac=frac+itopo(m,n)
              else
               frac=frac+odz
              End if
              if (k.ge.2) then
               itopo(m,n)=itopo(m,n)-odz
               If (itopo(m,n).le.0.)then
                itopo(m,n)=0.0
               End IF
              end if
           End do      !n
             Do n=(j-1)*c_row+1-(c_row/2.),j*c_row-(c_row/2.)
              m=(i-1)*c_col
              IF (itopo(m,n).le.odz) then
               frac=frac+itopo(m,n)
              else
               frac=frac+odz
              End if
              if (k.ge.2) then
               itopo(m,n)=itopo(m,n)-odz
               If (itopo(m,n).le.0.)then
                itopo(m,n)=0.0
               End IF
              end if
           End do      !n
           afba(i,j,k)=(frac*idy)/(2*odz*ody)
            If (k.eq.1) afba(i,j,k)=1.
          End do       !j
         End do        !i
        End do         !k
        !V
        itopo(:,:)=iitopo(:,:)
        Do k=1,out_kmax
         Do i=1,out_col
          Do j=2,out_row
           frac=0.0
           Do m=(i-1)*c_col+1,i*c_col
              n=(j-1)*c_row+1-(c_row/2.)
             IF(itopo(m,n).le.odz) then
              frac=frac+itopo(m,n)
             ELSE
              frac=frac+odz
             end if
                If (k.ge.2) then
                  itopo(m,n)=itopo(m,n)-odz
                   If (itopo(m,n).le.0.)then
                    itopo(m,n)=0.
                   End if
                End if
           End do      !m
           Do m=(i-1)*c_col+1,i*c_col
              n=(j-1)*c_row-(c_row/2.)
             IF(itopo(m,n).le.odz) then
              frac=frac+itopo(m,n)
             ELSE
              frac=frac+odz
             end if
                If (k.ge.2) then
                  itopo(m,n)=itopo(m,n)-odz
                   If (itopo(m,n).le.0.)then
                    itopo(m,n)=0.
                   End if
                End if
           End do      !m
           afbb(i,j,k)=(frac*idx)/(2*odz*odx)
           If (k.eq.1) afbb(i,j,k)=1.
          End do       !j
         End do        !i
        Enddo          !k
        !W
        itopo(:,:)=iitopo(:,:)
        Do k=1,out_kmax
         Do i=1,out_col
          Do j=2,out_row
           frac=0.0
           Do m=(i-1)*c_col+1,i*c_col
            Do n=(j-1)*c_row+1-(c_row/2.),j*c_row-(c_row/2.)
              IF(itopo(m,n).ge.odz)then
               frac=frac+1.
              End IF
              If (k.ge.3) then
                itopo(m,n)=itopo(m,n)-odz
                IF (itopo(m,n).lt.0.)then
                 itopo(m,n)=0.
                End if
              end if
            End do   !n
           End do    !m
            afbc(i,j,k)=(frac*idx*idy)/(odx*ody)
           If (k.eq.1 .or. k.eq.2) afbc(i,j,k)=1.
         End do      !j
        End do       !i
       End do        !k 

!  4.WW
        !U
        itopo(:,:)=iitopo(:,:)-(odz/2.)
        Do k=1,out_kmax
         Do i=1,out_col
          Do j=1,out_row
           frac=0.0
           Do n=(j-1)*c_row+1,j*c_row
              m=(i-1)*c_col+1
            If (itopo(m,n).le.0.)then
              itopo(m,n)=0.0
            End IF
              IF (itopo(m,n).le.odz) then
               frac=frac+itopo(m,n)
              else
               frac=frac+odz
              End if
              if (k.ge.2) then
               itopo(m,n)=itopo(m,n)-odz
              end if
           End do      !n
             Do n=(j-1)*c_row+1,j*c_row
              m=(i-1)*c_col
            If (itopo(m,n).le.0.)then
              itopo(m,n)=0.0
            End IF
              IF (itopo(m,n).le.odz) then
               frac=frac+itopo(m,n)
              else
               frac=frac+odz
              End if
              if (k.ge.2) then
               itopo(m,n)=itopo(m,n)-odz
              end if
           End do      !n
           afca(i,j,k)=(frac*idy)/(2*odz*ody)
            If (k.eq.1) afca(i,j,k)=1.
          End do       !j
         End do        !i
        End do         !k

        !V
        itopo(:,:)=iitopo(:,:)-(odz/2.)
        Do k=1,out_kmax
         Do i=1,out_col
          Do j=1,out_row
           frac=0.0
           Do m=(i-1)*c_col+1,i*c_col
              n=(j-1)*c_row+1

            If (itopo(m,n).le.0.)then
              itopo(m,n)=0.0
            End IF

             IF(itopo(m,n).le.odz) then
              frac=frac+itopo(m,n)
             ELSE
              frac=frac+odz
             end if
                If (k.ge.2) then
                  itopo(m,n)=itopo(m,n)-odz
                   If (itopo(m,n).le.0.)then
                    itopo(m,n)=0.
                   End if
                End if
           End do      !m
           Do m=(i-1)*c_col+1,i*c_col
              n=(j-1)*c_row
            If (itopo(m,n).le.0.)then
              itopo(m,n)=0.0
            End IF
             IF(itopo(m,n).le.odz) then
              frac=frac+itopo(m,n)
             ELSE
              frac=frac+odz
             end if
                If (k.ge.2) then
                  itopo(m,n)=itopo(m,n)-odz
                   If (itopo(m,n).le.0.)then
                    itopo(m,n)=0.
                   End if
                End if
           End do      !m
           afcb(i,j,k)=(frac*idx)/(2*odz*odx)
           If (k.eq.1) afcb(i,j,k)=1.
          End do       !j
         End do        !i
        Enddo          !k
        !W
        itopo(:,:)=iitopo(:,:)-(odz/2.)
        Do k=1,out_kmax-1
         Do i=1,out_col
          Do j=1,out_row
           frac=0.0
           Do m=(i-1)*c_col+1,i*c_col
            Do n=(j-1)*c_row+1,j*c_row
            If (itopo(m,n).le.0.)then
              itopo(m,n)=0.0
            End IF
              IF(itopo(m,n).ge.odz)then
               frac=frac+1.
              End IF
              If (k.ge.3) then
                itopo(m,n)=itopo(m,n)-odz
                IF (itopo(m,n).lt.0.)then
                 itopo(m,n)=0.
                End if
              end if
            End do   !n
           End do    !m
            afcc(i,j,k)=(frac*idx*idy)/(odx*ody)
           If (k.eq.1 .or. k.eq.2) afcc(i,j,k)=1.
         End do      !j
        End do       !i
       End do        !k

       do 100 k=1,out_kmax
       do 100 j=1,out_row
       do 100 i=1,out_col
        if(ucutcell(i,j,k).eq.0) then
        afaa(i,j,k)=1.
        afab(i,j,k)=1.
        afac(i,j,k)=1.
        afav(i,j,k)=1.

        afaa(i+1,j,k)=1.
        afab(i,j+1,k)=1.
        afac(i,j,k+1)=1.
        end if
        if(vcutcell(i,j,k).eq.0)then
        afba(i,j,k)=1.
        afbb(i,j,k)=1.
        afbc(i,j,k)=1.
        afbv(i,j,k)=1.

        afba(i+1,j,k)=1.
        afbb(i,j+1,k)=1.
        afbc(i,j,k+1)=1.
        end if
        if(cutcell(i,j,k).eq.0) then
        afca(i,j,k)=1.
        afcb(i,j,k)=1.
        afcc(i,j,k)=1.
        afcv(i,j,k)=1.

        afca(i+1,j,k)=1.
        afcb(i,j+1,k)=1.
        afcc(i,j,k+1)=1.
        end if


        if(ucutcell(i,j,k).eq.1) then
        afaa(i,j,k)=0.
        afab(i,j,k)=0.
        afac(i,j,k)=0.
        afav(i,j,k)=0.

        afaa(i+1,j,k)=0.
        afab(i,j+1,k)=0.
        afac(i,j,k+1)=0.
        end if
        if(vcutcell(i,j,k).eq.1)then
        afba(i,j,k)=0.
        afbb(i,j,k)=0.
        afbc(i,j,k)=0.
        afbv(i,j,k)=0.

        afba(i+1,j,k)=0.
        afbb(i,j+1,k)=0.
        afbc(i,j,k+1)=0.
        end if
        if(cutcell(i,j,k).eq.1) then
        afca(i,j,k)=0.
        afcb(i,j,k)=0.
        afcc(i,j,k)=0.
        afcv(i,j,k)=0.

        afca(i+1,j,k)=0.
        afcb(i,j+1,k)=0.
        afcc(i,j,k+1)=0.
        end if
  100  continue
!cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
!   PRINT COEFFICIENT FILE


        !Scalar
        Do k=1, out_kmax
          write(70,222) 'S =',k
          Do j=2, out_row-1
            write(70,3333) (cutcell(i,j,k), i=2,out_col-1)
          End do
        End do


        !U
        Do k=1, out_kmax
          write(70,222) 'U =',k
          Do j=2, out_row-1
            write(70,3333) (ucutcell(i,j,k), i=2,out_col-1)
          End do
        End do


        !V
        Do k=1, out_kmax
          write(70,222) 'V =',k
          Do j=2, out_row-1
            write(70,3333) (vcutcell(i,j,k), i=2,out_col-1)
          End do
        End do

        !Scalar
        !Do k=1, out_kmax
        !write(70,222) 'S =',k
        !write(70,3333) ((cutcell(i,j,k),i=2,out_col-1),j=2,out_row-1)
        !End do


        !U       
        !Do k=1, out_kmax
        !write(70,222) 'U =',k
        !write(70,3333) ((ucutcell(i,j,k),i=2,out_col-1),j=2,out_row-1)
        !End do

        !V
        !Do k=1, out_kmax
        !write(70,222) 'V =',k
        !write(70,3333) ((vcutcell(i,j,k),i=2,out_col-1),j=2,out_row-1)
        !End do

        Do k=1, out_kmax
         write(80,222) 'U =',k
        DO  j=2, out_row-1
          write(80,2222) (1.-1.*afsa(i,j,k), i=2,out_col-1) !2~imax3
        End Do
        End do

        Do k=1, out_kmax
         write(80,222) 'V =',k
        Do j=2, out_row-1
          write(80,2222) (1.-1.*afsb(i,j,k), i=2,out_col-1)
        End Do
        End do

        Do k=1, out_kmax
         write(80,222) 'W =',k
        Do j=2, out_row-1
          write(80,2222) (1.-1.*afsc(i,j,k), i=2,out_col-1)
        End Do
        End do

        Do k=1, out_kmax
         write(80,222) 'S =',k
        Do j=2, out_row-1
          write(80,2222) (1.-1.*afsv(i,j,k), i=2,out_col-1)
        End Do
        End do
        Do k=1, out_kmax
         write(80,222) 'uu=',k
        DO  j=2, out_row-1
          write(80,2222) (1.-1.*afaa(i,j,k), i=2,out_col-1)
        End Do
        End do

        Do k=1, out_kmax
         write(80,222) 'uv=',k
        Do j=2, out_row-1
          write(80,2222) (1.-1.*afab(i,j,k), i=2,out_col-1)
        End Do
        End do

        Do k=1, out_kmax
         write(80,222) 'uw=',k
        Do j=2, out_row-1
          write(80,2222) (1.-1.*afac(i,j,k), i=2,out_col-1)
        End Do
        End do

        Do k=1, out_kmax
         write(80,222) 'us=',k
        Do j=2, out_row-1
          write(80,2222) (1.-1.*afav(i,j,k), i=2,out_col-1)
        End Do
        end do

        Do k=1, out_kmax
         write(80,222) 'vu=',k
        DO  j=2, out_row-1
          write(80,2222) (1.-1.*afba(i,j,k), i=2,out_col-1)
        End Do
        End do

        Do k=1, out_kmax
         write(80,222) 'vv=',k
        Do j=2, out_row-1
          write(80,2222) (1.-1.*afbb(i,j,k), i=2,out_col-1)
        End Do
        End do

        Do k=1, out_kmax
         write(80,222) 'vw=',k
        Do j=2, out_row-1
          write(80,2222) (1.-1.*afbc(i,j,k), i=2,out_col-1)
        End Do
        End do

        Do k=1, out_kmax
         write(80,222) 'vs=',k
        Do j=2, out_row-1
          write(80,2222) (1.-1.*afbv(i,j,k), i=2,out_col-1)
        End Do
        End do

        Do k=1, out_kmax
         write(80,222) 'wu=',k
        DO  j=2, out_row-1
          write(80,2222) (1.-1.*afca(i,j,k), i=2,out_col-1)
        End Do
        End do

        Do k=1, out_kmax
         write(80,222) 'wv=',k
        Do j=2, out_row-1
          write(80,2222) (1.-1.*afcb(i,j,k), i=2,out_col-1)
        End Do
        End do

        Do k=1, out_kmax
         write(80,222) 'ww=',k
        Do j=2, out_row-1
          write(80,2222) (1.-1.*afcc(i,j,k), i=2,out_col-1)
        End Do
        End do

        Do k=1, out_kmax
         write(80,222) 'ws=',k
        Do j=2, out_row-1
          write(80,2222) (1.-1.*afcv(i,j,k), i=2,out_col-1)
        End Do
        End do

      END SUBROUTINE TOP
