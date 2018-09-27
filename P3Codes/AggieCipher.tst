// This file is part of www.nand2tetris.org
// and the book "The Elements of Computing Systems"
// by Nisan and Schocken, MIT Press.
// File name: projects/03/AggieCipher.tst

load AggieCipher.hdl,
output-file AggieCipher.out,
compare-to AggieCipher.cmp,
output-list in%B1.4.1 out%B1.4.1;

set in %B0000,
tick,
tock,
output;

set in %B1110,
tick,
tock,
output;

set in %B1101,
tick,
tock,
output;

set in %B1100,
tick,
tock,
output;

set in %B1011,
tick,
tock,
output;

set in %B1010,
tick,
tock,
output;

set in %B1001,
tick,
tock,
output;

set in %B1000,
tick,
tock,
output;

set in %B0111,
tick,
tock,
output;

set in %B0110,
tick,
tock,
output;

set in %B0101,
tick,
tock,
output;

set in %B0100,
tick,
tock,
output;

set in %B0011,
tick,
tock,
output;

set in %B0010,
tick,
tock,
output;

set in %B0001,
tick,
tock,
output;

set in %B0000,
tick,
tock,
output;

set in %B0000,
tick,
tock,
output;
