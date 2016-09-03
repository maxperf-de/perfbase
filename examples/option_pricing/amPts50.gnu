r = 0.1
sigma = 0.4
sig2half = sigma*sigma/2.0
E = 10.
T = 2.0

max(x, y) = (x>y)?x:y

d1(x) = (log(x/E)+(r+sig2half)*T)/(sigma*sqrt(T))

d2(x) = (log(x/E)+(r-sig2half)*T)/(sigma*sqrt(T))

N(x) = 1.-0.5*erfc(x/sqrt(2.))

blackscholes(x) = E*exp(-r*T)*N(-d2(x)) - x*N(-d1(x))

set title "American put"
set xlabel "S [$]"
set ylabel "P [$]"

set terminal postscript eps enhanced color

plot [7:20] "amopt_T2.dat" ti"Crank-Nicolson, 1000 gridpoints" w l,blackscholes(x) ti "European put","apc_T2.dat"u ($1):(blackscholes($1)+$2) ti "single realisation APC"

#plot [7:20] "amopt_T2.dat" ti"Crank-Nicolson, 1000 gridpoints" w l,blackscholes(x) ti "European put", "amopt.dat"ti "MC 20 gridpoints, 180 transitions"w p pt 5 ps 1,"apc_T2.dat"u ($1):(blackscholes($1)+$2) ti "single realisation APC",max(E-x,0.0)

#plot [7:20] "../../FD/am_nG1000.dat" ti"FD, 1000 gridpoints" w l,blackscholes(x) ti "European put", "amopt.dat"ti "MC 30 gridpoints, 600 transitions"w p pt 5 ps 1,"apc_T2.dat"u ($1):(blackscholes($1)+$2) ti "single realisation APC",1. w l 1,0.98 w l 1,max(E-x,0.0)

#plot[:15] "../../FD/am_nG1000.dat" ti"1000 gridpoints" w l,blackscholes(x) ti "European put", "amopt.dat"w p pt 5 ps 1,"apc_T2.dat"u ($1):(blackscholes($1)+$2) ti "APC",max(E-x,0.0)
# "../../FD/am_nG50.dat"

set out "mcAdjointCorr.ps"
set term post "Arial" 22
replot
!cp mcAdjointCorr.ps  $HOME/MyPub/Finance/AdjProc/figs
set term x11
replot

print blackscholes(12.)
