"""
Parse a Betterment statement PDF and produce QIF files for import
into Moneydance or other financial software.

https://github.com/dandrake/betterment-pdf-to-qif
"""

import collections
import datetime
import fileinput
import subprocess
import sys
import re

DEBUG = True
    
mon_to_num = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6, 'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}

ticker_to_name = {
    'BNDX': 'Total International Bond ETF',
    'VBR': 'Vanguard Small-Cap Value ETF',
    'VTI': 'Vanguard Total Stock Market ETF',
    'VTV': 'Vanguard Value ETF',
    'LQD': 'iShares iBoxx $ Investment Grade Corporate Bond ETF',
    'VEA': 'FTSE Developed Markets ETF',
    'VWO': 'Vanguard FTSE Emerging Markets ETF',
    'MUB': 'Municipal Bonds ETF',
    'VWOB': 'Vanguard Emerging Markets Government Bond ETF',
    'VOE': 'Vanguard Mid-Cap Value ETF',
    'VTIP': 'Vanguard Short-Term Inflation-Protected Securities ETF',
    'SHV': 'iShares Short Treasury Bond ETF',
}

_GOALS = {('BUILD', 'WEALTH'), ('SAFETY', 'NET')}

# Betterment bug with goal names on non-Quarterly Statement PDFs
new_goals = set()
for goal in _GOALS:
    new_goals.add(tuple(word.title() for word in goal) + ('Goal',))
_GOALS.update(new_goals)

_SHARE_ACTIVITY = {
    ('Quarterly', 'Activity', 'Detail'),
    ('Dividend', 'Reinvestment', 'Detail'),
    ('Transaction', 'Detail'),
}

def parse_dividend_payment(line):
    """
    we look for lines like

    ['May', '7', '2015', 'MUB', 'iShares', 'National', 'AMT-Free', 'Muni', 'Bond', 'ETF', '$0.05']

    date, fund, description, amount
    """
    try:
        ret = {'type': 'div pay'}
        ret['date'] = datetime.date(month=mon_to_num[line[0]],
                                    day=int(line[1]),
                                    year=int(line[2]))
        ret['ticker'] = line[3]
        ret['desc'] = ' '.join(line[4:-1])
        ret['amount'] = line[-1].lstrip('-$').replace(',', '')

        # these are here to raise exceptions if something weird happens
        ticker_to_name[ret['ticker']]
        float(ret['amount'])
    except:
        raise ValueError
    return ret
    
def parse_share_activity(line):
    """tricky thing here is that you have two kinds of lines:
    
    ['Apr', '2', '2015', 'Dividend', 'Reinvestment', 'Stocks', '/', 'VTV', '$83.55', '0.008', '$0.66', '0.592', '$49.48']

    and
    
    ['Stocks', '/', 'VTI', '$107.45', '0.004', '$0.45', '0.460', '$49.46']

    so we return a dictionary with the keys we can figure out and leave
    it to the caller to track the necessary state.

    Transaction types are "Dividend Reinvestment" and "Automatic
    Deposit" and "Advisory Fee". (Others I'll add later.)

    Returns a dictionary with keys (a subset of!):

    * date: datetime.date object
    * ticker: ticker symbol
    * share_price
    * shares
    * amount
    * type: right now, one of:
        * div buy: buying after a dividend payment
        * buy: buying after a deposit
        * fee sell: selling shares to pay advisory fee

    Values except the date are all strings.
    """
    try:
        ret = {}
        # just looking for the slash and the type identifies the lines we want
        slash = line.index('/')
        if line[slash - 1] == 'Stocks' or line[slash - 1] == 'Bonds':
            if slash > 1:
                print('Parsing first half: ' + str(line))
                ret['date'] = datetime.date(month=mon_to_num[line[0]],
                                            day=int(line[1]),
                                            year=int(line[2]))
                desc = line[3:slash - 1]
                ret['desc'] = ' '.join(desc)
                if 'Reinvestment' in desc:
                    ret['type'] = 'div buy'
                elif 'Deposit' in desc:
                    ret['type'] = 'buy'
                elif 'Fee' in desc:
                    ret['type'] = 'fee sell'
                elif 'Transfer' in desc:
                    ret['type'] = 'transfer'
                else:
                    ret['type'] = 'unknown'
                ret.update(parse_share_activity(line[slash - 1:]))
                return ret
            elif slash == 1:
                print('Parsing second half: ' + str(line))
                ret['ticker'] = line[2]
                ret['raw_share_price'] = line[3].replace('$', '').replace(',', '')
                ret['share_price'] = line[3].lstrip('-$').replace(',', '')
                # QIF files don't include negative amounts; they list
                # everything as positive and use the transaction type to
                # figure out the rest. So okay to strip minus signs.
                ret['raw_amount'] = line[5].replace('$', '').replace(',', '')
                ret['amount'] = line[5].lstrip('-$').replace(',', '')

                # We calculate the number of shares on our own; see
                # discussion in the README.
                ret['shares'] = '{:.6f}'.format(float(ret['amount']) /
                                                float(ret['share_price']))
                ret['raw_shares'] = '{:.6f}'.format(float(ret['raw_amount']) /
                                                float(ret['raw_share_price']))
                if abs(float(ret['shares']) - abs(float(line[4]))) >= .001:
                    print('wonky number of shares:')
                    print('PDF says', line[4])
                    print('transaction:', ret)

                # check if ticker ok
                ret['ticker_name'] = ticker_to_name[ret['ticker']]

                # for now, ignore the last two fields (total shares and
                # total value of that security)
                print('Got ' + str(ret))
                return ret
            else:
                # / in position 0???
                if DEBUG:
                    print('slash at start!?')
                    print(line)
                raise ValueError
        else:
            # / not preceded by 'Stocks' or 'Bonds'
            raise ValueError
    except:
        raise ValueError

def parse_text(txt):
    """parse the text we get from the statement PDF (as a list of list of
    strings) and return a list of transactions -- dictionaries.
    """
    goal = None
    trans_type = None
    transactions = []
    for linenum, line in enumerate(txt):
        #if line == ['BUILD', 'WEALTH'] or line == ['SAFETY', 'NET']:
        if tuple(line) in _GOALS:
            goal = ' '.join(line[:2]).title()
            trans_type = None
            if DEBUG: print(goal + ' starts line', linenum) 
        elif line[:2] == ['CASH', 'ACTIVITY']:
            goal = None
            if DEBUG: print('done with goals line', linenum)

        if goal is not None:
            if trans_type == 'share':
                try:
                    #if DEBUG: print('parsing share line: ' + str(line))
                    trans = parse_share_activity(line)
                    if DEBUG: print('got trans:', trans)
                    try:
                        trans_date = trans['date']
                    except KeyError:
                        trans['date'] = trans_date
                    try:
                        sub_trans_type = trans['type']
                    except KeyError:
                        trans['type'] = sub_trans_type
                    try:
                        desc = trans['desc']
                    except KeyError:
                        trans['desc'] = desc
                    if DEBUG: print('share trans:', trans)
                    trans['goal'] = goal
                    transactions.append(trans)
                except ValueError:
                    pass

            if line == ['Dividend', 'Payment', 'Detail']:
                trans_type = 'dividend'
            elif tuple(line) in _SHARE_ACTIVITY:
                if DEBUG: print('classified line as share: ' + str(line))
                trans_type = 'share'

    # now we want, as we would say in SQL,
    #   SELECT goal, date, SUM(amount)
    #   WHERE type = 'fee sell'
    #   GROUP BY date;
    # and to add corresponding fee-transfer transactions
    fees = collections.defaultdict(lambda: 0.0)
    for trans in [t for t in transactions if t['type'] == 'fee sell']:
        fees[(trans['goal'], trans['date'])] += float(trans['amount'])
    for goal, date in fees.keys():
        transactions.append({'goal': goal,
                             'date': date,
                             'type': 'fee pay',
                             'amount': fees[(goal, date)]})
    return transactions

def fmt_date(t):
    return t['date'].strftime('%m/%d/%Y')

def create_csv(transactions, filename):
    with open(filename, 'a') as handle:
        handle.write(
            ','.join([
                'Goal','Date','Ticker','Ticker Name','Description','Shares',
                'Share Price','Amount']) + '\n')
        for trans in transactions:
            if 'shares' in trans:
                handle.write(
                    ','.join([
                        trans['goal'], str(trans['date']), trans['ticker'],
                        trans['ticker_name'], trans['desc'], trans['raw_shares'],
                        trans['raw_share_price'], trans['raw_amount']]) + '\n')

def empty_file(filename):
    open(filename, 'w').close()
    
def get_text_array(filename):
    text = subprocess.check_output(
        ['pdftotext', '-nopgbrk', '-layout', input_file, '-'])
    return [line.decode('utf-8') for line in text.splitlines()]

if __name__ == '__main__':
    # we want a list of lines, each split on whitespace
    empty_file('transactions.csv')
    transactions = []
    for input_file in sys.argv[1:]:
        print('reading file ' + input_file)
        txt = get_text_array(input_file)

        if DEBUG:
            with open(sys.argv[1] + '-debug.txt', 'w') as f:
                f.write(
                    '\n'.join([str(line.split()) for line in 
                    txt if not re.match('^\s*$', line)]))

        transactions.extend(parse_text([
            line.split() for line in txt if not re.match('^\s*$', line)]))

    create_csv(transactions, 'transactions.csv')
