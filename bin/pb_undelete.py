# perfbase - (c) 2004 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_undelete - Delete data from an experiment, or delete a complete experiment
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

from pb_common import *

import sys
import getopt
from os import F_OK, R_OK, getenv, access
from string import lower, upper, strip

# DBAPI implementation to access PostgreSQL
import psycopg2 as psycopg


# globals
exp_name = None
run_id = None
db_info = { 'host':None, 'port':None, 'name':None, 'user':None, 'password':None }

def print_help():
    """Print the specific help information for this tool."""
    print "perfbase undelete - Un-delete a previously deleted run"
    print "Arguments:"
    print "--exp=<exp>, -e <exp>       Experiment to delete (or to delete something from)"
    print "--run=<run>, -r <run>       ID of the run to be un-deleted from <exp>"
    print_generic_dbargs()

    return


def parse_cmdline(argv):
    global db_info
    global run_id, exp_name

    # parse arguments
    try:
        options, values = getopt.getopt(argv, 'hVve:r:', ['dbhost=', 'dbport=', 'dbname=', 'dbuser=',
                                                          'dbpasswd=', 'help', 'version', 'exp=',
                                                          'run=', 'debug', 'sqltrace'])
    except getopt.GetoptError, error_msg:
        print "#* ERROR: Invalid argument found:", error_msg
        print "   Use option '--help' for a list of valid arguments."
        sys.exit(1)

    for o, v in options:
        if o in ("-v", "--verbose"):
            set_verbose(True)
            continue
        if o in ("--debug"):
            set_debug(True)
            continue
        if o in ("-h", "--help"):
            print_help()
            sys.exit()
            continue
        if o in ("-V", "--version"):
            print_version()
            sys.exit()
            continue
        if o == "--sqltrace":
            set_sql_trace(True)
            continue

        if o in ("-e", "--exp"):
            exp_name = v
            continue
        if o in ("-r", "--run"):
            run_id = v
            try:
                all_digits = int(run_id)
            except ValueError:
                print "#* ERROR: invalid run ID '%s' - has to be an integer value" % run_id
                sys.exit(1)                
            continue

        if o == "--dbhost":
            db_info['host'] = v
            continue
        if o == "--dbport":
            db_info['port'] = v
            continue
        if o == "--dbname":
            db_info['name'] = lower(v)
            continue
        if o == "--dbuser":
            db_info['user'] = v
            continue
        if o == "--dbpasswd":
            db_info['password'] = v
            continue

    if not exp_name:
        print "#* ERROR: Experiment name needs to be specified explicitely."
        print "          Option --help shows syntax. Exiting."
        sys.exit(1)
    if not run_id:
        print "#* ERROR: ID of run needs to be specified."
        print "          Option --help shows syntax. Exiting."
        sys.exit(1)

    return


def undel_run(db, run_id):
    crs = db.cursor()

    # check that the specified run does exist and is not active
    sqlexe(crs, "SELECT active FROM run_metadata WHERE index = %s", None, (run_id, ))
    if crs.rowcount == 0:
        print "#* ERROR: run %s does not exist." % run_id
        sys.exit(1)
    if crs.fetchone()[0]:
        print "#* WARNING: run %s was not deleted." % run_id
        sys.exit(0)

    sqlexe(crs, "UPDATE run_metadata SET active = true WHERE index = %s", None, (run_id, ))
    db.commit()
    if be_verbose():
        print "#* Run %s was set active in experiment '%s'" % (run_id, exp_name)

    crs.close()
    return

   
def main(argv=None):
    global run_id, exp_name
    global db_info
       
    if argv is None:
        argv = sys.argv[1:]   
    parse_cmdline(argv)

    get_dbserver(None, db_info)

    # Check that the experiment does exist
    db_info['name'] = lower("pb_"+exp_name)
    db = open_db (db_info)
    if db == None:
        sys.exit(1)

    undel_run(db, run_id)
    db.close()

    return    


if __name__ == "__main__":
    run_mode = getenv("PB_RUNMODE")
    if run_mode == "debug":
        main()
    else:
        try:
            main()
        except KeyboardInterrupt:
            print ""
            print "#* User aborted delete operation."
        except psycopg.ProgrammingError, error_msg:
            if error_msg.args[0].find('permission denied') > 0:
                print "#* ERROR: user '%s' has insufficient privileges to access experiment '%s'" \
                      % (db_info['user'], exp_name)
            else:
                print "#*", error_msg
            sys.exit(1)
    sys.exit(0)
