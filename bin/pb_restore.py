# perfbase - (c) 2004-2006 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_restore - restore an experiment to a database server from a dump file
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
import re
import getopt

from pb_common import *
from pb_extend import *

# globals
dump_file = None
exp_name = None
do_force = False
db_info = { 'host':None, 'port':None, 'name':None, 'user':None, 'password':None }

def print_help():
    """Print the specific help information for this tool."""
    print "perfbase restore - Restore an experiment from a dump file"
    print "Synopsis:"
    print "  perfbase restore --file=<file> [--exp=<exp>]"
    print "Arguments:"
    print "--file=<file>, -f <file>    Filename of the dump"
    print "--exp=<exp>, -e <exp>       Name of the experiment to be restored. For automatically"
    print "                            named dump files, the name is determined from the dump file name "
    print "--force                     Try to restore even if the database already exists"
    print_generic_dbargs()
    return


def parse_cmdline(argv):
    """Set default values for externally controled parameters, and set them according to parameters."""
    global exp_name, dump_file, db_info, do_force
  
    # parse arguments
    try:
        options, values = getopt.getopt(argv, 'hVve:f:', ['dbhost=', 'dbport=', 'dbuser=', 'dbpasswd=',
                                                          'help', 'version', 'debug', 'verbose', 'exp=',
                                                          'file=', 'force'])
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
            sys.exit()
            continue
        if o in ("--version", "-V"):
            print_version()
            sys.exit()
            continue
        if o == "--debug":
            set_debug(True)
            continue

        if o in ("-e", "--exp"):
            if not exp_name:
                exp_name = v
            else:
                print "#* ERROR: specifiy exactly one experiment"
                sys.exit(1)
            continue
        if o in ("-f", "--file"):
            if not dump_file:
                dump_file = v
            else:
                print "#* ERROR: specifiy exactly one dump filename"
                sys.exit(1)
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
            exp_name = v
            continue
        if o == "--dbuser":
            db_info['user'] = v
            continue
        if o == "--dbpasswd":
            db_info['password'] = v
            continue

    if dump_file is None:
        print "#* ERROR: specifiy exactly one dump file name (option --file)"
        sys.exit(1)         
    if exp_name is None:
        # Derive the experiment name from the dump file name. Does only work if the dump file
        # name was generated by the dump command itself.
        if dump_file.find('__') == -1:
            print "#* ERROR: can not determine experiment name from dump file name."
            sys.exit(1)

        # This matching could be done smarter!?
        regexp = re.compile('__')
        exp_name = regexp.split(dump_file)[0]
        regexp = re.compile('/')
        exp_name = regexp.split(exp_name)[-1]
        if len(exp_name) == 0:            
            print "#* ERROR: can not determine experiment name from dump file name."
            sys.exit(1)
    return


def main(argv=None):
    global db_info, exp_name, dump_file, do_force
    
    if argv is None:
        argv = sys.argv[1:]   
    parse_cmdline(argv)

    # Determine the database server to be used. Preference of the parameters:
    # cmdline > environment > default
    get_dbserver(None, db_info)
    db_info['name'] = "pb_" + exp_name.lower()
    if be_verbose():
        print "#* accessing database server on '%s:%d' as user '%s'" % (db_info['host'],\
                                                                        db_info['port'],\
                                                                        db_info['user'])
    if not os.access(dump_file, os.F_OK):
        print "#* ERROR: dump file '%s' does not exist. Aborting." % dump_file
        sys.exit(1)
    if not os.access(dump_file, os.R_OK):
        print "#* ERROR: dump file '%s' is not readable. Aborting." % dump_file
        sys.exit(1)

    # Check if the database does already exist.Will not restore to existing database
    # if do_force is not set!
    db = open_db(db_info, True)
    if db is not None:
        if not do_force:
            print "#* ERROR: database '%s' does already exist. Aborting." % db_info['name']
            sys.exit(1)
    else:
        # Need to create the database if it does not exist. 
        if not create_db(db_info, None):
            print "#* ERROR: could not create database '%s'. Aborting." % db_info['name']
            sys.exit(1)
    db = open_db(db_info)
    crs = db.cursor()

    # Check if we need to install custom datatype(s) first
    for custom_type in ['version_nbr']:
        fo = os.popen("gunzip -c %s | grep %s," % (dump_file, custom_type))
        grep_output = fo.readlines()
        if len(grep_output) > 0:
            if not eval("create_datatype_%s" % custom_type)(db, crs):
                # Creating new datatype failed
                print "#* ERROR: can not install custom SQL type '%s'" % custom_type
                sys.exit(1)

    db.commit()
    crs.close()
    db.close()
    
    # Run the restore command. We don't want to unzip the dump file on disc.
    rc = None
    cmd_args = "-h %s -p %d -U %s -d %s" % (db_info['host'], db_info['port'], \
                                            db_info['user'], db_info['name'])
    try:
        # pg_restore uses non-SQL format; we use pure SQL
        # restore_cmd = "gunzip -c %s | pg_restore %s" % (dump_file, cmd_args)
        restore_cmd = "gunzip -c %s | psql %s" % (dump_file, cmd_args)
        if be_verbose():
            print "#* restoring experiment '%s' from '%s'" % (exp_name, dump_file)
        if do_debug():
            print "#* restore command is '%s'" % restore_cmd
        fo = os.popen(restore_cmd, 'r')
    except:
        print "#* ERROR: can not run restore command. Make sure 'psql' and 'gunzip' are found in $PATH."
        sys.exit(1)
    restore_output = fo.readlines()
    rc = fo.close()
    if rc is not None:
        print "#* ERROR: restore operation for experiment '%s' failed:" % exp_name
        for i in range(len(restore_output)):
            print restore_output[i]                        
        sys.exit(1)

    print "#* Experiment '%s' was restored from dump file '%s'" % (exp_name, dump_file)
    return


if __name__ == "__main__":
    run_mode = getenv("PB_RUNMODE")
    if run_mode == "debug":
        main()
    else:
        try:
            main()
        except KeyboardInterrupt:
            print "#* User aborted restore operation."
            sys.exit(0)
        except StandardError, error_msg:
            print "#* ERROR:", error_msg
            sys.exit(1)
    sys.exit(0)
