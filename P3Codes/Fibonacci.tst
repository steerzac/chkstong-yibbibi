//Fibonacci test file

// File name: projects/03/Fibonacci.tst

load Fibonacci.hdl,
output-file Fibonacci.out,
compare-to Fibonacci.cmp,
output-list time%S2.3.1 f0%D1.4.1 f1%D1.4.1 enable1%B4.1.4 enable2%B4.1.4 enable3%B4.1.4 out%D1.4.1;

//write the initial values to the first two registers
//and write the result to the third register
set f0 %D0,
set f1 %D1,
set enable1 1,
set enable2 1,
set enable3 1,
set msel 0,
tick,
output,
tock,
//to see how fibonacci number changes, only keep this following output for each cycle
output;


//update the new sum
set msel 1,
//transfer value of reg1 to reg2, and do not affect reg3
set enable1 0,
set enable2 0,
tick,
output;
tock,
output;

set enable1 1,
set enable2 1,
set enable3 1,
tick,
output;
tock,
output;

//transfer value of reg3 to reg1, do not affect reg2
set enable1 0,
set enable2 0,
tick,
output;
tock,
output;

set enable1 1,
set enable2 1,
set enable3 1,
tick,
output;
tock,
output;

//transfer value of reg3 to reg1, do not affect reg2
set enable1 0,
set enable2 0,
tick,
output;
tock,
output;

set enable1 1,
set enable2 1,
set enable3 1,
tick,
output;
tock,
output;

//transfer value of reg3 to reg1, do not affect reg2
set enable1 0,
set enable2 0,
tick,
output;
tock,
output;

set enable1 1,
set enable2 1,
set enable3 1,
tick,
output;
tock,
output;

//transfer value of reg3 to reg1, do not affect reg2
set enable1 0,
set enable2 0,
tick,
output;
tock,
//output;

set enable1 1,
set enable2 1,
set enable3 1,
tick,
output;
tock,
output;

//transfer value of reg3 to reg1, do not affect reg2
set enable1 0,
set enable2 0,
tick,
output;
tock,
output;

set enable1 1,
set enable2 1,
set enable3 1,
tick,
output;
tock,
output;

//transfer value of reg3 to reg1, do not affect reg2
set enable1 0,
set enable2 0,
tick,
output;
tock,
output;

set enable1 1,
set enable2 1,
set enable3 1,
tick,
output;
tock,
output;

//transfer value of reg3 to reg1, do not affect reg2
set enable1 0,
set enable2 0,
tick,
output;
tock,
output;

set enable1 1,
set enable2 1,
set enable3 1,
tick,
output;
tock,
output;

//transfer value of reg3 to reg1, do not affect reg2
set enable1 0,
set enable2 0,
tick,
output;
tock,
output;

set enable1 1,
set enable2 1,
set enable3 1,
tick,
output;
tock,
output;

//transfer value of reg3 to reg1, do not affect reg2
set enable1 0,
set enable2 0,
tick,
output;
tock,
output;

set enable1 1,
set enable2 1,
set enable3 1,
tick,
output;
tock,
output;

//transfer value of reg3 to reg1, do not affect reg2
set enable1 0,
set enable2 0,
tick,
output;
tock,
output;

set enable1 1,
set enable2 1,
set enable3 1,
tick,
output;
tock,
output;

//transfer value of reg3 to reg1, do not affect reg2
set enable1 0,
set enable2 0,
tick,
output;
tock,
output;

set enable1 1,
set enable2 1,
set enable3 1,
tick,
output;
tock,
output;

//transfer value of reg3 to reg1, do not affect reg2
set enable1 0,
set enable2 0,
tick,
output;
tock,
output;

set enable1 1,
set enable2 1,
set enable3 1,
tick,
output;
tock,
output;

//transfer value of reg3 to reg1, do not affect reg2
set enable1 0,
set enable2 0,
tick,
output;
tock,
output;

set enable1 1,
set enable2 1,
set enable3 1,
tick,
output;
tock,
output;

//transfer value of reg3 to reg1, do not affect reg2
set enable1 0,
set enable2 0,
tick,
output;
tock,
output;

set enable1 1,
set enable2 1,
set enable3 1,
tick,
output;
tock,
output;

//transfer value of reg3 to reg1, do not affect reg2
set enable1 0,
set enable2 0,
tick,
output;
tock,
output;

set enable1 1,
set enable2 1,
set enable3 1,
tick,
output;
tock,
output;

//transfer value of reg3 to reg1, do not affect reg2
set enable1 0,
set enable2 0,
tick,
output;
tock,
output;

