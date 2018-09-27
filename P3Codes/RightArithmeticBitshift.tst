// This file is part of www.nand2tetris.org
// and the book "The Elements of Computing Systems"
// by Nisan and Schocken, MIT Press.
// File name: projects/03/RightArithmeticBitshift.tst

//Important test Cases include:
// load = 0, in = 1, tick, tock, output shift by 1 bit
// load = 1, in = 0, tick, tock, output shift by 1 bit and MSB is replaced with 0
// load = 1, in = 1, tick, tock, output shift by 1 bit and MSB is replaced with 1
// load = 0, in = 0, tick, tock, output shift by 1 bit
// load = 1, in = 1, reset = 1, tick, tock, output becomes 0000

load RightArithmeticBitshift.hdl,
output-file RightArithmeticBitshift.out,
compare-to RightArithmeticBitshift.cmp,
output-list in%B1.1.1 out%B1.4.1;


set reset 1,
tick,
tock,
set reset 0;

set in 1,
set load 1,
tick,
tock,
set load 0;
tick,
tock,
output;

set reset 1,
tick,
tock,
set reset 0,
output;

set in 1,
set load 1,
tick,
tock,
output,

set in 0;
tick,
tock,
output,

set in 1,
tick,
tock,
output,

set in 0,
tick,
tock,
output,

tick,
tock,
output,

set in 1,
set load 0,
tick,
tock,
output,

set load 1,
tick,
tock,
output,

tick,
tock,
output,

set in 0,
set load 0,
tick,
tock,
output,

tick,
tock,
output,

set load 1,
tick,
tock,
output,

set in 1,
set load 1,
tick,
tock,
output,

set in 0,
set load 1,
tick,
tock,
output,

set in 1,
set load 0,
tick,
tock,
output,

set reset 1,
tick,
tock,
output,


