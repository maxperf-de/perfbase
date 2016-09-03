# perfbase - (c) 2004 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_delete - Delete data from an experiment, or delete a complete experiment
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
do_force = False
do_ask = True
exp_name = None
run_id = None
pset_id = None
db_info = { 'host':None, 'port':None, 'name':None, 'user':None, 'password':None }

def print_help():
    """Print the specific help information for this tool."""
    print "perfbase delete - Delete an experiment, or a run of an experiment,"
    print "                  from a perfbase database server."
    print "Arguments:"
    print "--exp=<exp>, -e <exp>       Experiment to delete (or to delete something from)"
    print "--run=<run>, -r <run>       ID of the run to be deleted from <exp>"
    print "--pset=<pset>, -p <pset>    ID of the parameter set to be deleted from <exp>"
    print "--dontask                   Delete an experiment without confimation"
    print "--force                     Delete experiment also if database is inconsistent,"
    print "                            and don't complain if the experiment does not exist."
    print_generic_dbargs()

    return


def parse_cmdline(argv):
    global db_info
    global do_force, do_ask, run_id, exp_name, pset_id

    # parse arguments
    try:
        options, values = getopt.getopt(argv, 'hVve:r:p:', ['dbhost=', 'dbport=', 'dbname=', 'dbuser=',
                                                            'dbpasswd=', 'help', 'version', 'exp=',
                                                            'run=', 'pset=', 'dontask', 'force',
                                                            'debug', 'sqltrace'])
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
        if o in ("-p", "--pset"):
            if run_id:
                print "#* ERROR: delete either a run or a parameter set! "
                sys.exit(1)                
            pset_id = v
            continue
        if o in ("-r", "--run"):
            if pset_id:
                print "#* ERROR: delete either a run or a parameter set! "
                sys.exit(1)                
            run_id = v
            try:
                all_digits = int(run_id)
            except ValueError:
                print "#* ERROR: invalid run ID '%s' - has to be an integer value" % run_id
                sys.exit(1)                
            continue
        if o == "--dontask":
            do_ask = False
            continue
        if o == "--force":
            do_force = True
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

    return


def del_run(db):
    global do_force, do_ask, run_id, exp_name

    crs = db.cursor()

    # check that the specified run does exist
    sqlexe(crs, "SELECT active FROM run_metadata WHERE index = %s", None, (run_id, ))
    if crs.rowcount == 0:
        print "#* ERROR: run %s does not exist." % run_id
        sys.exit(1)
    if not crs.fetchone()[0]:
        print "#* WARNING: run %s is already deleted." % run_id
        sys.exit(0)

    if do_ask and do_force:
        print "*** ALL DATA WILL BE LOST WHEN DELETING A RUN:"
        print "    Really delete run %s from experiment '%s'? <yes/NO>" % (run_id, exp_name)
        if cmp(strip(upper(sys.stdin.readline())), "YES"):
            print "NOT deleting anything from experiment '%s'. Exiting." % exp_name
            crs.close()
            return

    # Delete a single run from the experiment. Actually, it will not be
    # removed from the database, but only set 'inactive'. It can be removed
    # using the '--force' argument, or 'pb_check --clean'
    if do_force:
        sqlexe(crs, "DELETE FROM run_metadata WHERE index = %s", None, (run_id, ))
        sqlexe (crs, "DELETE FROM rundata WHERE pb_run_index=%d" % run_id)
        db.commit()
        if be_verbose():
                print "#* Run %s was removed from experiment '%s'" % (run_id, exp_name)
    else:
        sqlexe(crs, "UPDATE run_metadata SET active = false WHERE index = %s", None, (run_id, ))
        db.commit()
        if be_verbose():
            print "#* Run %s was set inactive in experiment '%s'" % (run_id, exp_name)

    crs.close()
    return


def del_pset(db):
    global do_force, do_ask, exp_name, pset_id

    crs = db.cursor()

    # check that the specified pset does exist
    sqlexe(crs, "SELECT * FROM param_sets WHERE set_name = %s", None, (pset_id, ))
    if crs.rowcount == 0:
        print "#* ERROR: parameter set %s does not exist." % pset_id
        sys.exit(1)

    if do_ask:
        print "*** ALL PARAMTER DATA WILL BE LOST WHEN DELETING A PARAMETER SET:"
        print "    Really delete parameter set %s from experiment '%s'? <yes/NO>" % (pset_id, exp_name)
        if cmp(strip(upper(sys.stdin.readline())), "YES"):
            print "NOT deleting anything from experiment '%s'. Exiting." % exp_name
            crs.close()
            return

    sqlexe(crs, "DELETE FROM param_sets WHERE set_name = %s", None, (pset_id, ))
    db.commit()
    if be_verbose():
        print "#* Parameter set %s was removed from experiment '%s'" % (pset_id, exp_name)

    crs.close()
    return


def del_exp(db, db_info):
    global do_ask, exp_name

    # Check again if user is about to delete a complete experiment!
    if do_ask:
        print "*** ALL DATA WILL BE LOST WHEN DELETING AN EXPERIMENT:"
        print "    Really delete experiment '%s'? <yes/NO>" % exp_name
        if cmp(strip(upper(sys.stdin.readline())), "YES"):
            print "NOT deleting anything from experiment '%s'. Exiting." % exp_name
            return

    db.close()            
    if not drop_db(db_info):
        print "#* ERROR: deleting database of experiment '%s' failed. Exiting." % exp_name
        sys.exit(1)

    return

    
def main(argv=None):
    global do_force, do_ask, run_id, exp_name, pset_id
    global db_info
       
    if argv is None:
        argv = sys.argv[1:]   
    parse_cmdline(argv)

    get_dbserver(None, db_info)

    # Check that the experiment does exist
    db_info['name'] = lower("pb_"+exp_name)
    db = open_db (db_info, do_force)
    if db == None:
        if not do_force:
            print "#* ERROR: Can not open experiment database '%s'." % db_info['name']
            print "          Does the experiment '%s' exist?" % exp_name
            sys.exit(1)
        else:
            sys.exit(0)

    if run_id:
        del_run(db)
        db.close()
    elif pset_id:
        del_pset(db)
        db.close()
    else:
        del_exp(db, db_info)

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
