#!/bin/bash
#PBS -S /bin/bash
#PBS -N <JOB_NAME>
#PBS -j oe
#PBS -q intel
#PBS -l walltime=1440:00:00
#PBS -l nodes=1:ppn=9
#PBS -V
 
set -o pipefail

cd ${PBS_O_WORKDIR}
 
n=0
for inf in *.in
do
        n=$(($n+1))
        mpirun -np 9 pw.x -i ${inf} &> ${inf//in/out} || exit $?
        grep -E '^[[:space:]]*![[:space:]]+total[[:space:]]+energy[[:space:]]*=' ${inf//in/out} |awk -v var="$n" '{print var "\t" $5}' >> energy.dat || exit $?
done
 
