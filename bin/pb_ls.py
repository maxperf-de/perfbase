# perfbase - (c) 2004-2005 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_ls - A simple tool to list the runs within an experiment. For more complex tasks,
#         use pb_find.
#
#     This file is part of perfbase.
#
#     perfbase is free software; you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation; either version 2 of the License, or
#     (at your option) any later version.
#
#     perfbase is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public License
#     along with perfbase; if not, write to the Free Software
#     Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import sys
import os
import getopt

from os import F_OK, R_OK, getenv, access
from os.path import basename, realpath, getmtime
from time import localtime, strftime
from datetime import datetime
from string import find, split, whitespace, lower, upper, strip, rstrip
from xml.etree import ElementTree
from random import seed, randint

from pb_common import *

# DBAPI implementation to access PostgreSQL
import psycopg2 as psycopg

# global variables
meta_mapping = { 'syno':'synopsis', 'desc':'description',
                 'crtr':'creator', 'tspf':'performed',
                 'tsin':'created', 'rows':None,
                 'indx':'index', 'file':'input_name',
                 'ninp':'nbr_inputs' }

ls_meta = []
ls_meta_long = ['indx', 'crtr', 'tspf']
ls_show = []

db_info = { 'host':None, 'port':None, 'name':None, 'user':None, 'password':None }
exp_name = None
long_ls = False
distinct_ls = False
show_rows = False
nvals = 1

def print_help():
    """Print the specific help information for this tool."""
    print "perfbase ls - List runs inside a perfbase experiment"
    print "Arguments:"
    print "--exp=<exp>, -e <exp>       Search inside experiment <exp>."
    print "-l, --long                  Long listing"
    print "--show=<name[,name,...]>, -s <name[,name,...]>"
    print "                            For the listed runs, show the variable <name>."
    print "                            Multiple occurrences are possible and considered in the order"
    print "                            in which they appear."
    print "--meta=<label[,label,...]>, -m <label[,label,...]>"
    print "                            Specify meta information to be displayed for all runs."
    print "                             Valid labels are:"
    print "                             syno   synopsis"
    print "                             desc   description"
    print "                             crtr   creator of the run"
    print "                             tspf   timestamp when experiment was performed"
    print "                             tsin   timestamp of data import"
    print "                             rows   number of data rows"
    print "                             indx   run index"
    print "                             file   name of input file(s)"
    print "                             ninp   number of input file(s)"
    print "--nvals=<n>, -n <n>         Show up to 'n' distinct content elements per value"
    print "--all, -a                   Show all distinct content elements per value"
    print "--distinct, -d              List distinct content elements for the specified values"
    print_generic_dbargs()
    return

def parse_cmdline(argv):
    """Set default values for externally controled parameters, and set them according to parameters."""
    global exp_name, long_ls, distinct_ls, ls_meta, ls_meta_long, show_rows, nvals
    global db_info

    exp_name = getenv("PB_EXPERIMENT")

    argv2 = argv_preprocess(argv)
    n_params = param_count(argv2)
    
    # parse arguments
    try:
        options, values = getopt.getopt(argv2, 'hVve:s:m:n:lad', ['dbhost=', 'dbport=', 'dbuser=', 'dbpasswd=',
                                                                  'help', 'version', 'verbose', 'exp=', 'all',
                                                                  'show=', 'nvals=', 'meta=', 'long', 'debug',
                                                                  'distinct', 'sqltrace'])
    except getopt.GetoptError, error_msg:
        print "#* ERROR: Invalid argument found:", error_msg
        print "   Use option '--help' for a list of valid arguments."
        sys.exit(1)

    for o, v in options:
        if o in ("-v", "--verbose"):
            set_verbose(True)
            continue
        if o in ("-h", "--help"):
            print_help()
            sys.exit(0)
        if o in ("--version", "-V"):
            print_version()
            sys.exit(0)
        if o == "--debug":
            set_debug(True)
            continue
        if o == "--sqltrace":
            set_sql_trace(True)
            continue

        if o in ("-e", "--exp"):
            exp_name = v
            continue
        if o in ("-l", "--long"):
            long_ls = True
            continue
        if o in ("-d", "--distinct"):
            distinct_ls = True
            continue
        if o in ("-s", "--show"):
            ls_show.extend(v.split(','))
            continue
        if o in ("-n", "--nvals"):
            try:
                nvals = int(v)
            except ValueError:
                print "#* ERROR: invalid argument '%s' to option '%s'" % (v, o)
                sys.exit(1)
            continue
        if o in ("-a", "--all"):
            nvals = -1
            continue
        if o in ("-m", "--meta"):
            for l in v.split(','):            
                if l == 'rows':
                    show_rows = True
                if len(l) > 0:
                    ls_meta.append(l)
            continue

        if o == "--dbhost":
            db_info['host'] = v
            continue
        if o == "--dbport":
            db_info['port'] = v
            continue
        if o == "--dbname":
            exp_name = v
            continue
        if o == "--dbuser":
            db_info['user'] = v
            continue
        if o == "--dbpasswd":
            db_info['password'] = v
            continue

    if len(ls_meta) == 0 and len(ls_show) == 0:
        ls_meta.extend(['indx', 'syno', 'desc'])
    if long_ls:
        for f in ls_meta_long:
            if not f in ls_meta:
                ls_meta.append(f)

    if exp_name is None:
        print "#* ERROR: no experiment name specified"
        print "   Use option '--help' for help."
        sys.exit(1)
    return


def show_distinct(db):
    global ls_meta, ls_show, show_rows, nvals

    crs = db.cursor()
    for m in ls_meta:
        if m == "rows":
            continue
        sqlexe(crs, "SELECT DISTINCT %s FROM run_metadata WHERE active = 't'" % meta_mapping[m])

        print "%s:" % m
        for r in crs.fetchall():
            if len(str(r[0])) > 0:
                print "  %s" % str(r[0])

    for v in ls_show:
        cntnt = get_all_content(db, v)
        print "%s:" % v,
        out = []
        for c in cntnt:
            out.append(c)
        out.sort()
        print out

    crs.close()
    return
    

def main(argv=None):
    global distinct_ls, ls_meta, ls_show, show_rows, nvals
    global db_info
    
    if argv is None:
        argv = sys.argv[1:]   
    parse_cmdline(argv)

    db_info['name'] = lower("pb_" + exp_name)
    get_dbserver(None, db_info)

    try:
        db = psycopg.connect ("host=%s port=%d user=%s dbname=%s password=%s" % \
                              (db_info['host'], db_info['port'], db_info['user'],
                               db_info['name'], db_info['password']))        
        if not check_db_version(db, exp_name):
            raise DatabaseError, "version mismatch of experiment database and commandline tools"
    except psycopg.Error, error_msg:
        if error_msg.args[0].find('database "%s" does not exist' % db_info['name']) > 0:
            print "#* ERROR: experiment '%s' not found with database server on '%s:%d'. " \
                  % (exp_name, db_info['host'], db_info['port'])
            print "   Use command 'perfbase info --all' to list all available experiments."
        elif error_msg.args[0].find('permission denied') > 0:
            print "#* ERROR: user '%s' has insufficient privileges to access experiment '%s'" \
                  % (db_info['user'], exp_name)
        else:
            print "#* ERROR: could not access database server on host '%s:%d'." % (db_info['host'], db_info['port'])
            print "   error message: ", error_msg
        sys.exit(1)

    if distinct_ls:
        show_distinct(db)
        db.close()
        return

    crs = db.cursor()
    # Query meta information. We always need the index, although we might not list it.
    header = []
    meta_rows = []
    sql_cmd = "SELECT index,"
    for f in ls_meta:
        if not meta_mapping.has_key(f):
            raise StandardError, "Invalid meta label '%s'" % f
        if meta_mapping[f] is None:
            continue
        header.append(f)
        sql_cmd += meta_mapping[f] + ","
    sql_cmd = sql_cmd[:-1] + " FROM run_metadata WHERE active='t'"
    if len(ls_meta) > 0 and meta_mapping[ls_meta[0]] is not None:
        sql_cmd += " ORDER BY " + meta_mapping[ls_meta[0]] + " ASC"
    else:
        sql_cmd += " ORDER BY index ASC"
    if do_debug():
        print "DEBUG: query '%s'" % sql_cmd
    sqlexe(crs, sql_cmd)
    if crs.rowcount == 0:
        print "#* experiment '%s' contains no run data." % exp_name
        sys.exit(0)
    meta_nim = build_name_idx_map(crs)
    meta_rows = crs.fetchall()    

    # get separate list of run indexes
    sqlexe(crs, "SELECT index FROM run_metadata WHERE active='t'")
    run_idx = crs.fetchall()

    if show_rows:
        run_rows = {}
        header.append('rows')

        filter_str = "WHERE "
        for r in run_idx:
            filter_str += "pb_run_index=%d OR " % r
        filter_str = filter_str[:-3]
        
        sqlexe(crs, "SELECT COUNT(*) FROM rundata %s" % filter_str)
        run_rows[r[0]] = crs.fetchone()[0]

    # query data from the individual runs
    print_rows = {}
    mult_vars = []
    once_vars = []
    if len(ls_show) > 0:
        # Check if the variable does exist and does only occur once! We can not list variables
        # with changing content. However,  variables which are not 'only_once' *can* be listed
        # if their content does not change!
        for s in ls_show:
            sqlexe(crs, "SELECT name FROM exp_values WHERE name = '%s' AND only_once = 't'" % s)
            if crs.rowcount == 0:
                # Check for constant content.
                if be_verbose():
                    print "#* WARNING: variable '%s' can contain multiple values per run." % s
                mult_vars.append(s)
            else:
                once_vars.append(s)
            header.append(s)

        # now get the data
        sql_cmd = "SELECT run_index,"
        for s in once_vars:
            sql_cmd += "%s," % s
        sql_cmd = sql_cmd[:-1] + " FROM rundata_once"
        if do_debug():
            print "DEBUG: query '%s'" % sql_cmd
        sqlexe(crs, sql_cmd)            
        nim = build_name_idx_map(crs)

        # and store it to make it suitable for output
        for row in crs.fetchall():
            rundata = {}
            for s in once_vars:
               rundata[s] = row[nim[s.lower()]]

            # check if we can get unique values even for multiply-occuring variables
            for s in mult_vars:
                sqlexe(crs, "SELECT DISTINCT %s FROM rundata WHERE pb_run_index=%d" % (s, row[nim['run_index']]))
                if crs.rowcount == 0:
                    rundata[s] = "#no_data#"
                elif crs.rowcount <= nvals or nvals < 0:
                    rundata[s] = ""
                    for d in crs.fetchall():
                        rundata[s] += str(d[0])+'|'
                    rundata[s] = rundata[s][:-1]
                else:
                    rundata[s] = "#%dvalues#" % crs.rowcount

            print_rows[row[nim['run_index']]] = rundata

    # output what we got
    if be_verbose():
        for h in header:
            print "%s\t" % str(h),
        print

    max_idx = len(meta_rows)
    if max_idx == 0:
        max_idx = len(print_rows)

    for idx in range(max_idx):        
        for f in ls_meta:
            if f != 'rows':
                print "%s\t" % meta_rows[idx][meta_nim[meta_mapping[f]]],
            else:
                print "%s\t" % run_rows[meta_rows[idx][0]],
        for s in ls_show:
            print "%s\t" % print_rows[meta_rows[idx][0]][s],
        print

    crs.close()
    db.close()
    return


if __name__ == "__main__":
    run_mode = getenv("PB_RUNMODE")
    if run_mode == "debug":
        main()
    else:
        try:
            main()
        except psycopg.ProgrammingError, error_msg:
            if error_msg.args[0].find('permission denied') > 0:
                print "#* ERROR: user '%s' has insufficient privileges to access experiment '%s'" \
                      % (db_info['user'], exp_name)
            else:
                print "#*", error_msg
            sys.exit(1)
        except DatabaseError, error_msg:
            print "#* Could not access any data."
            print " ", error_msg
            sys.exit(1)
        except KeyboardInterrupt:
            print "#* User aborted operation."
        except SpecificationError, error_msg:
            print "#* Invalid operation:"
            print "  ", error_msg
            sys.exit(1)
        except StandardError, error_msg:
            print "#* ERROR: Abort by exception:"
            print "  ", error_msg
            sys.exit(1)
    sys.exit(0)
