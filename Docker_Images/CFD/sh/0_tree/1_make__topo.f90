        Program Tree_input
        Implicit None
        include '../data/Domain/tree_domain.inc'
        Integer ,Parameter :: imax1=imax+1,jmax1=jmax+1,kmax1=kmax+1
        Integer ,Parameter :: imax2=imax+2,jmax2=jmax+2,kmax2=kmax+2
        real,dimension(topo_col,topo_row) :: input_topo
        real,dimension(topo_inner_col,topo_inner_row) :: cut_topo
        Integer,dimension(imax2,jmax2) :: frtp,denst
        real,dimension(imax2,jmax2) :: theight
        real,dimension(imax2,jmax2) :: LAD, frac,itopo 
        INTEGER,dimension(imax2,jmax2,kmax) :: itc, ita, itb
        
        INTEGER :: i,j,k,m,n,l,t
        INTEGER :: k_start,k_end
        INTEGER :: ii,jj,iii,jjj
        real :: isum 
        character(len=40) :: fmt_i, fmt_f

        write(fmt_i,'(a1,i0,a3)') '(', imax2, 'I1)'
        write(fmt_f,'(a1,i0,a5)') '(', imax2, 'f6.2)'

        ita(:,:,:) = 1
        itb(:,:,:) = 1
        itc(:,:,:) = 1

        LAD(:,:) = 0.
        frac(:,:) = 0.

        open(10, FILE='./cut/tree_height_model.txt')
        open(11, FILE='./cut/tree_frtp_cd_model.txt')
        open(12, FILE='./cut/tree_dnst_cd_model.txt')
        open(13, FILE='./../0_TOPO/cut/cut_auto_10m.txt')

        open(21, FILE='./result_tree/TREE.top')
        open(22, FILE= './result_tree/LAD.txt')
        open(23, FILE='./result_tree/fraction.txt')

        do j=1,jmax2
         read(10,*) (theight(i,j),i=1,imax2)
         read(11,*) (frtp(i,j),i=1,imax2)
         read(12,*) (denst(i,j),i=1,imax2)
        end do
       
        do j=1,topo_row
         read(13,*) (input_topo(i,j),i=1,topo_col)
        end do        
      

        do j=1,topo_inner_row
        do i=1,topo_inner_col
            cut_topo(i,j) = input_topo(i+topo_halo_src,j+topo_halo_src)
        end do
        end do 
         
        do jj = 1, jmax
          do ii = 1, imax
           isum = 0.0
           do jjj = 1, topo_ratio
            do iii = 1, topo_ratio
              i = 1 + (ii-1)*topo_ratio + (iii-1)
              j = 1 + (jj-1)*topo_ratio + (jjj-1)
              isum = isum + cut_topo(i,j)
             end do
            end do
          itopo(ii+1, jj+1) = isum / real(topo_ratio*topo_ratio)
         end do
        end do
 
        do j=2,jmax1
         do i=2,imax1
         if(theight(i,j) .ne. 0.) then
 
          if(denst(i,j).eq.0) then
           frac(i,j) = 0.
          else if (denst(i,j).eq.1) then
           frac(i,j) = 0.33
          else if(denst(i,j) .eq.2) then
           frac(i,j) = 0.67
          else if (denst(i,j) .eq.3) then
           frac(i,j) = 1.0
          end if
          
         if(frtp(i,j).eq.1) then
          LAD(i,j) = 4.02/(0.39*theight(i,j))
         else if(frtp(i,j).eq.2) then
          LAD(i,j) = 5.18/(0.39*theight(i,j))
         else if(frtp(i,j).eq.3) then
          LAD(i,j) = 3.23/(0.39*theight(i,j))
         else if(frtp(i,j).eq.4) then 
          LAD(i,j) = 3.95/(0.39*theight(i,j))
         end if
         
        end if 
       end do
      end do
        
        do j=2, jmax1
         do i=2, imax1
         if(theight(i,j).ne.0.) then

           n =  int( (itopo(i,j)+0.61*theight(i,j)) / dz)+2
           m =  int( (itopo(i,j)+     theight(i,j)) / dz)+2
           if (m .ge. 1 .and. n .le. kmax) then
            k_start = max(1,n)
            k_end = min(kmax,m)
            do  k = k_start,k_end
             itc(i,j,k) = 0
            end do
           end if
         end if
           itc(i,j,1) = 0 
         end do
        end do 
       
        do 100 k=1, kmax
        do 100 j=2, jmax1
        do 100 i=2, imax1
          ita(i,j,k) = itc(i,j,k)
          itb(i,j,k) = itc(i,j,k)
        if(itc(i,j,k).eq.1 .and. itc(i+1,j,k).eq.0) then
            ita(i,j,k) = 0
            LAD(i,j) = LAD(i+1,j)
            frac(i,j) = frac(i+1,j)
        end if
        if(itc(i,j-1,k).eq.0 .and. itc(i,j,k).eq.1) then
            ita(i,j,k) = 0
            LAD(i,j) = LAD(i,j-1)
            frac(i,j) = frac(i,j-1)
        end if
  100 continue
        

        do k=1, kmax
         WRITE(21,222) 'S =',k
         WRITE(21,fmt_i) ((itc(i,j,k),i=1,imax2),j=1,jmax2)
        end do

        do k=1, kmax
         WRITE(21,222) 'U =',k
         WRITE(21,fmt_i) ((ita(i,j,k),i=1,imax2),j=1,jmax2)
        end do

        do k=1, kmax
         WRITE(21,222) 'V =',k
         WRITE(21,fmt_i) ((itb(i,j,k),i=1,imax2),j=1,jmax2)
        end do

        WRITE(22,fmt_f) ((LAD(i,j),i=1,imax2),j=1,jmax2)
        WRITE(23,fmt_f) ((frac(i,j),i=1,imax2),j=1,jmax2) 
  222 FORMAT(A4,I3)
 
      End program 
