# Parse Betterment's PDF statements, output CSV

[Betterment](http://betterment.com) is a nice brokerage service but they
don't provide transaction data in any parseable, structured format. The
Python script here will parse your quarterly statement, deposit and dividend
PDFs and produce CSV files suitable for importing into an accounting program.

This is super hackish and brittle and this should really just be thought
of as a starting point, and not as a genuinely usable tool. 

## Requirements

You'll need Python 3 and the `pdftotext` utility. I use Ubuntu Linux and
`pdftotext` is available in the `poppler-utils` package. In some other
OS, you'll need to work out on your own how to extract text from the
PDF.

## How to run

`// Will output to a file called transactions.csv`  
`python3 betterment-pdf-to-csv.py *.pdf`  

## On rounding and number of shares

Betterment seems to round the number of shares transacted and
internally record more precision. I have seen on my statement the
following:

Reported transactions (all purchases):

| price | num shares | amount |
|-------|------------|--------|
| 92.20 |       .057 | 5.30   |
| 92.62 |       .057 | 5.30   |
| 93.05 |       .055 | 5.10   |

Betterment reported a total increase of .170 shares -- but

    .057 + .057 + .055 = .169!

However, if you use the amount and the price, you get a total of
0.169516035336005 shares, which rounds to .170. 

In another case, I saw this:

* Reported starting balance: .005 shares (1 previous transaction)
* Reported total purchases: .010 shares (2 transactions of .005 shares)
* Reported ending balance: .014 shares
 
Yikes! Using price and amounts, you get (to 6 decimal places)

    .56/120.41 + .56/122.8 + .62/120.67 = 0.004651 + 0.004560 + 0.005138 
                                        = 0.014349

So it does look like they are using units smaller than .001 shares.

Because their reported number of shares isn't accurate, this program
ignores that number and calculates the number of shares to six decimal
places using the share price and dollar amount.
