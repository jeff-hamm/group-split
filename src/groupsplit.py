import os
from urllib.parse import urlparse, parse_qs
from urllib.parse import urlparse
import click
import re
import csv
import sys
import json
import pickle
import pprint
import urllib
import hashlib
import logging
import optparse
import requests
import subprocess
import os
import webbrowser
import oauthlib.oauth1
from money import Money
from pprint import pprint
from datetime import datetime
from tabulate import tabulate

LOGGING_DISABELED = 100
log_levels = [LOGGING_DISABELED, logging.CRITICAL, logging.ERROR,
              logging.WARNING, logging.INFO, logging.DEBUG]
# Adapted from:
# https://docs.python.org/2/howto/logging.html#configuring-logging
# create logger
logger = logging.getLogger(__name__)

# create console handler and set level to debug
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

# create formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# add formatter to ch
ch.setFormatter(formatter)

# add ch to logger
logger.addHandler(ch)
logging.basicConfig(format='%(asctime)s %(message)s', datefmt='%m/%d/%Y %I:%M:%S %p')

def split(total, num_people):
    """
    Splits a total to the nearest whole cent and remainder
    Total is a Money() type so no need to worry about floating point errors
    return (2-tuple): base amount owed, remainder of cents which couldn't be evenly split

    Example: >>> split(1.00, 6) 
    (0.16, 0.04)
    """
    base = total * 100 // num_people / 100
    extra = total - num_people * base
    assert base * num_people + extra == total, "InternalError:" + \
    " something doesnt add up here: %d * %d + %d != %d" %(base, num_people, extra, total)
    return base, extra

def do_hash(msg):
    m = hashlib.md5()
    m.update(msg.encode('utf-8'))
    return m.hexdigest()

class Splitwise:
    """
    Client for communicating with Splitwise api
    """
    def __init__(self, api_client='oauth_client.pkl', ckey=None,csecret=None):
        if os.path.isfile(api_client):
            with open(api_client, 'rb') as oauth_pkl:
                self.client = pickle.load(oauth_pkl)
        else:
            self.get_client(ckey,csecret)

    def get_client_auth(self,ckey,csecret):
        ckey = os.environ.get('ckey') or ckey
        csecret = os.environ.get('csecret') or csecret
        if os.path.isfile("consumer_oauth.json"):
            with open("consumer_oauth.json", 'rb') as oauth_file:
                consumer = json.load(oauth_file)
                self.ckey = ckey or consumer['consumer_key']
                self.csecret = csecret or consumer['consumer_secret']
        else:
            self.ckey = ckey or click.prompt("Your splitwise oauth key (from https://secure.splitwise.com/oauth_clients)")
            self.csecret = csecret or click.prompt("Your splitwise oauth secret")
            json_file={'consumer_key':self.ckey or 'YOUR KEY HERE',
                           'consumer_secret':self.csecret or 'YOUR SECRET HERE'}
            print(json_file)
            with open("consumer_oauth.json", "w", encoding="utf8") as oauth_file:
                json.dump(json_file, oauth_file)
        if(not self.ckey or not self.csecret):
            exit("go to https://secure.splitwise.com/oauth_clients to obtain your keys."+
                 "place them in consumer_oauth.json or in ckey/csecret")
            

    def get_client(self,ckey,csecret):
        self.get_client_auth(ckey,csecret)
        client = oauthlib.oauth1.Client(self.ckey, client_secret=self.csecret)
        uri, headers, body = client.sign("https://secure.splitwise.com/api/v3.0/get_request_token",
                                         http_method='POST')
        r = requests.post(uri, headers=headers, data=body)
        resp = r.text.split('&')
        if(len(resp) < 2):
            logger.error(r.text)
            logger.error("go to https://secure.splitwise.com/oauth_clients to obtain your keys.")
            self.client = None
            return;
        else:
            logger.debug(r.text)

        oauth_token = resp[0].split('=')[1]
        oauth_secret = resp[1].split('=')[1]
        uri = "https://secure.splitwise.com/authorize?oauth_token=%s" % oauth_token
#        logger.debug(uri, oauth_secret)
        webbrowser.open_new(uri)

        # proc = subprocess.Popen(['python', 'server.py'], stdout=subprocess.PIPE)
        # stdout, stderr = proc.communicate()
        # if stderr:
        #     exit(stderr)

        verifier_input = click.prompt(f'Navigate to \n{uri}\n then copy the url from the success page in the browser window:\n')
 #       logger.debug(verifier_input)
        parsed_url = urlparse(verifier_input)
        verifier_input=parse_qs(parsed_url.query)['oauth_verifier'][0]

        client = oauthlib.oauth1.Client(self.ckey, client_secret=self.csecret,
                                        resource_owner_key=oauth_token,
                                        resource_owner_secret=oauth_secret,
                                        verifier=verifier_input)
                                        #verifier=stdout.strip()) #bYpMPennhuz6bqMRZXd8

        uri, headers, body = client.sign("https://secure.splitwise.com/api/v3.0/get_access_token",
                                         http_method='POST')
        resp = requests.post(uri, headers=headers, data=body)
#        print(resp.text)
        tokens = resp.text.split('&')
        oauth_token = tokens[0].split('=')[1]
        oauth_secret = tokens[1].split('=')[1]
        client = oauthlib.oauth1.Client(self.ckey, client_secret=self.csecret,
                                        resource_owner_key=oauth_token,
                                        resource_owner_secret=oauth_secret,
                                        verifier=verifier_input)
                                        #verifier=stdout.strip())
        with open('oauth_client.pkl', 'wb') as pkl:
            pickle.dump(client, pkl)
        self.client = client

    def api_call(self, url, http_method):
        uri, headers, body = self.client.sign(url, http_method=http_method)
        resp = requests.request(http_method, uri, headers=headers, data=body)
        return resp.json()

    def get_id(self):
        if not hasattr(self, "my_id"):
            resp = self.api_call("https://secure.splitwise.com/api/v3.0/get_current_user", 'GET')
            self.my_id = resp['user']['id']
        return self.my_id

    def get_groups(self):
        resp = self.api_call("https://secure.splitwise.com/api/v3.0/get_groups", 'GET')
        return resp['groups']

    def post_expense(self, uri):
        resp = self.api_call(uri, 'POST')
        if resp["errors"]:
            sys.stderr.write( "URI:")
            sys.stderr.write(uri)
            pprint(resp, stream=sys.stderr)
        else:
            sys.stdout.write(".")
            sys.stdout.flush()

    def delete_expense(self, expense_id):
        return self.api_call("https://secure.splitwise.com/api/v3.0/delete_expense/%s" % expense_id, 'POST')

    def get_expenses(self, after_date="", limit=0, allow_deleted=True):
        params = {'limit': limit, "updated_after": after_date}
        paramsStr = urllib.urlencode(params)
        resp = self.api_call("https://secure.splitwise.com/api/v3.0/get_expenses?%s" % (paramsStr), 'GET')
        if not allow_deleted:
            resp['expenses'] = [exp for exp in resp['expenses'] if exp['deleted_at'] is None]
        return resp['expenses']

class CsvSettings():
    def __init__(self, rows):
        print("These are the first two rows of your csv")
        print("\n".join([str(t) for t in rows[0:2]]))
        print("Colnum numbers start at 0")
        self.date_col = input("Which column has the date?")
        self.amount_col = input("Which column has the amount?")
        self.desc_col = input("Which column has the description?")
        self.has_title_row = input("Does first row have titles? [Y/n]").lower() != 'n'
        self.newest_transaction = ''
        while True:
            try:
                self.local_currency = input("What currency were these transactions made in?").upper()
                test = Money("1.00", self.local_currency)  #pylint: disable=W0612
            except ValueError as err:
                print(err)
                print("Try again...")
            else:
                break
        self.remember = input("Remember these settings? [Y/n]").lower() != 'n'

    def __del__(self):
        if self.remember:
            with open("csv_settings.pkl", "wb") as pkl:
                pickle.dump(self, pkl)

    def record_newest_transaction(self, rows):
        if self.has_title_row:
            self.newest_transaction = do_hash(str(rows[1]))
        else:
            self.newest_transaction = do_hash(str(rows[0]))


class SplitGenerator():
    def __init__(self, options, args, api):
        csv_file = args[0]
        group_name = args[1]
        self.api = api
        self.options = options
        self.args = args
        with open(csv_file, 'r') as csvfile:
            reader = csv.reader(csvfile)
            self.rows = [x for x in reader]

        if os.path.isfile(options.csv_settings):
            with open(options.csv_settings, 'rb') as f:
                self.csv = pickle.load(f)
        elif os.path.isfile("/csv_settings.pkl"):
            with open("/csv_settings.pkl", 'rb') as f:
                self.csv = pickle.load(f)
        else:
            self.csv = CsvSettings(self.rows)

        if self.csv.has_title_row:
            self.rows = self.rows[1:]

        self.make_transactions()
        self.csv.record_newest_transaction(self.rows)
        self.get_group(group_name)
        self.splits = []
        self.ask_for_splits()

    def make_transactions(self):
        """
        Consume the row data from the csv file into a format which is easy to upload to splitwise
        Filter out all deposits (positive amounts)
        **change csvDateFormat to the format in your csv if necessary** 
        Further reading on date formats: https://docs.python.org/2/library/datetime.html#strftime-and-strptime-behavior
        """
        csvDateFormat="%Y-%m-%d"
        self.transactions = []
        for r in self.rows:
            # if not self.options.try_all and do_hash(str(r)) == self.csv.newest_transaction:
            #    break
            if float(r[int(self.csv.amount_col)]) > 0:
                self.transactions.append({
                    "date": datetime.strptime(r[int(self.csv.date_col)], csvDateFormat).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "amount": Money(r[int(self.csv.amount_col)], self.csv.local_currency),
                    "desc": re.sub(r'\s+', ' ', r[int(self.csv.desc_col)])
                }
                )

    def get_group(self, name):
        """
        Wrapper around splitwise api for retreiving groups
        by name. Handles error cases: multiple groups with same name, 
        no group found, group has no members.
        
        name: the name of your Splitwise group (case insensitive)
        """
        num_found = 0
        gid = ''
        members = {}
        groups = self.api.get_groups()
        for group in groups:
            if group['name'].lower() == name.lower():
                gid = group['id']
                members = [m['id'] for m in group['members'] if m['id'] != self.api.get_id()]
                num_found += 1

        if num_found > 1:
            exit("More than 1 group found with name:" + name)
        elif num_found < 1:
            exit("No matching group with name:" + name)
        elif len(members) < 1:
            exit("No members in group with name:" + name)

        self.members = members
        self.gid = gid

    def ask_for_splits(self):
        """
        Ask the user whether they would like to split a given expense and if so
        add it to tee list of transactions to upload to Splitwise. Gets final
        confirmation before returning.
        """
        print("Found {0} transactions".format(len(self.transactions)))
        i = 0
        for t in self.transactions:
            if self.options.yes or input("%d: %s at %s $%s. Split? [y/N]" % (i, t['date'], t['desc'], t['amount'])).lower() == 'y':
                self.splits.append(t)

        print("-" * 40)
        print("Your Chosen Splits")
        print("-" * 40)
        print(tabulate( self.splits, headers={"date":"Date", "amount":"Amount", "desc":"Description"} ))

        # Kill program if user doesn't want to submit splits
        assert self.options.yes or input( "Confirm submission? [y/N]" ).lower() == 'y', "User canceled submission"

    def __getitem__(self, index):
        """
        Implement an iterator for SplitGenerator
        for every split in self.splits, emit the URI needed
        to upload that split to Splitwise
        """
        s = self.splits[index]
        one_cent = Money("0.01", self.csv.local_currency)
        num_people = len(self.members) + 1
        base, extra = split(s['amount'], num_people)
        params = {
            "payment": 'false',
            "cost": s["amount"].amount,
            "description": s["desc"],
            "date": s["date"],
            "group_id": self.gid,
            "currency_code": self.csv.local_currency,
            "users__0__user_id": self.api.get_id(),
            "users__0__paid_share": s["amount"].amount,
            "users__0__owed_share": base.amount,
        }
        for i in range(len(self.members)):
            params['users__%s__user_id' % (i+1)] = self.members[i]
            params['users__%s__paid_share' % (i+1)] = 0
            params['users__%s__owed_share' % (i+1)] = (base + one_cent).amount if extra.amount > 0 else base.amount
            extra -= one_cent
        paramsStr = urllib.parse.urlencode(params)
        return "https://secure.splitwise.com/api/v3.0/create_expense?%s" % (paramsStr)

import os

def main():

    usage = "groupsplit.py [options] [splitwise group name]"
    parser = optparse.OptionParser(usage=usage)
    parser.add_option('-v', '--verbosity', default=2, dest='verbosity', help='change the logging level (0 - 6) default: 2')
    parser.add_option('-y','',default=False, action='store_true', dest='yes', help='split all transactions in csv without confirmation')
    parser.add_option('-d', '--dryrun', default=False, action='store_true', dest='dryrun', help='prints requests instead of sending them')
    parser.add_option('', '--csv-settings', default='csv_settings.pkl', dest='csv_settings', help='supply different csv_settings object (for testing mostly)')
    parser.add_option('', '--api-client', default='oauth_client.pkl', dest='api_client', help='supply different splitwise api client (for testing mostly)')
    parser.add_option('-a', '--all', default=False, action='store_true', dest='try_all', help='consider all transactions in csv file no matter whether they were already seen')
    options, args = parser.parse_args()
    logger.setLevel(log_levels[int(options.verbosity)])
    directory="/imports"
    if not os.path.exists(directory):
        os.makedirs(directory)
    os.chdir(directory)
    files=os.listdir(directory)
    if(not len(files)):
        print("No csv files found")
        return
    splitwise = Splitwise(options.api_client)
    if(not splitwise.client):
        return
    suffix=".csv"
    print(options)
    group = (args and len(args) and args[0]) or click.prompt("Splitwise group name?")
    for filename in files:
        if(filename.endswith(suffix)):
            if click.confirm(f"Do you want to import {filename}?", default=True):
                split_gen = SplitGenerator(options, [filename,group], splitwise)
                #print("Uploading splits")
                for uri in split_gen:
                    if options.dryrun:
                        #print(uri)
                        continue
                    splitwise.post_expense(uri)
                sys.stdout.write("\n")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
