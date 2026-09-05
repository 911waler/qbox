set grid
set xlabel "Number"
set ylabel "Total Energy (Ry)"
unset key
plot 'energy.dat' u 1:2 w lp lw 2 lc rgb "dark-blue" ps 1.5 pt 7,
pause -1
