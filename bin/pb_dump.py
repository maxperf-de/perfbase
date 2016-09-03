# perfbase - (c) 2004-2005 NEC Europe C&C Research Laboratories
#            Joachim Worringen <joachim@ccrl-nece.de>
#
# pb_dump - dump an experiment to a dump file
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
import re

from pb_common import *

# globals
exp_name = None
db_info = { 'host':None, 'port':None, 'name':None, 'user':None, 'password':None }

def print_help():
    """Print the specific help information for this tool."""
    print "perfbase dump - Dump an experiment to a dump file."
    print "Synopsis:"
    print "  perfbase dump [--file=<file>] --exp=<exp>"
    print "Arguments:"
    print "--exp=<exp>, -e <exp>       Name of the experiment to be dumped."
    print "--file=<file>, -f <file>    Filename of the dump. A file name is created"
    print "                            automatically this option is omitted."
    print_generic_dbargs()
    return


def parse_cmdline(argv):
    """Set default values for externally controled parameters, and set them according to parameters."""
    global exp_name, dump_file, db_info
  
    # parse arguments
    try:
        options, values = getopt.getopt(argv, 'hVve:f:', ['dbhost=', 'dbport=', 'dbuser=', 'dbpasswd=',
                                                          'help', 'version', 'debug', 'verbose', 'exp=',
                                                          'file=', 'sqltrace'])
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
        if o == "--sqltrace":
            set_sql_trace(True)
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

    if not exp_name:
        exp_name = getenv("PB_EXPERIMENT")
        if not exp_name:
            print "#* ERROR: specifiy exactly one experiment (option --exp)"
            sys.exit(1)         
    if not dump_file:
        # Construct a file name which contains the experiment name and a time stamp.
        # First, we need to normalize the experiment name to use at most one underscore
        # next to each other.
        regexp = re.compile('_*')
        dump_file = ''
        for tok in regexp.split(exp_name):
            dump_file += tok + '_'
        dump_file = dump_file[:-1] + '__' + mk_timestamp('%Y%m%d_%H%M') + '.sql'
    return


def main(argv=None):
    global db_info, exp_name, dump_file
    
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
                                                                        db_info['user'],)
    if os.access(dump_file, os.F_OK):
        print "#* ERROR: dump file '%s' does already exist. Aborting." % dump_file
        sys.exit(1)
    if os.access(dump_file+".gz", os.F_OK):
        print "#* ERROR: dump file '%s' does already exist. Aborting." % (dump_file+".gz")
        sys.exit(1)

    # Run the pg_dump command.
    rc = None
    cmd_args = "-h %s -p %d -U %s" % (db_info['host'], db_info['port'], db_info['user'])
    try:
        dump_cmd = 'pg_dump %s %s > %s' % (cmd_args, db_info['name'], dump_file)
        if be_verbose():
            print "#* dumping experiment '%s' to '%s'" % (exp_name, dump_file+".gz")
        if do_debug():
            print "#* dump command is '%s'" % dump_cmd
        fo = os.popen(dump_cmd, 'r')
    except:
        print "#* ERROR: can not run dump command. Make sure 'pg_dump' is found in $PATH."
        sys.exit(1)
    pg_dump_output = fo.readlines()
    rc = fo.close()
    if rc is not None:
        print "#* ERROR: dump operation failed (return code %d) - deleting dump file." % rc
        # We don't want exceptions here.
        if os.access(dump_file, os.F_OK):
            os.remove(dump_file)
        sys.exit(1)

    # To be sure...
    if not os.access(dump_file, os.F_OK):
        print "#* ERROR: dump operation failed, no dump file was created."
        sys.exit(1)

    try:
        if be_verbose():
            print "#* compressing output file"
        fo = os.popen('gzip %s' % dump_file, 'r')
    except:
        print "#* ERROR: can not run 'gzip'. File integrity could not be verified - deleting dump file."
        # We don't want exceptions here.
        if os.access(dump_file, os.F_OK):
            os.remove(dump_file)
        sys.exit(1)
    rc = fo.close()
    if rc is not None:
        print "#* ERROR: compression operation failed (return code %d) - deleting dump file." % rc
        # We don't want exceptions here.
        if os.access(dump_file, os.F_OK):
            os.remove(dump_file)
        if os.access(dump_file+".gz", os.F_OK):
            os.remove(dump_file+".gz")
        sys.exit(1)

    # Test for file integrity!
    try:
        if be_verbose():
            print "#* testing integrity"
        fo = os.popen('gzip -t %s' % (dump_file+".gz"), 'r')
    except:
        print "#* ERROR: can not run 'gzip'. File integrity could not be verified - deleting dump file."
        # We don't want exceptions here.
        if os.access(dump_file+".gz", os.F_OK):
            os.remove(dump_file+".gz")
        sys.exit(1)
    gzip_output = fo.readlines()
    rc = fo.close()
    if rc is not None or len(gzip_output) > 0:
        print "#* ERROR: dump file '%s' failed integrity test:" % dump_file
        for i in range(len(gzip_output)):
            print gzip_output[i]                        
        print "          Deleting dump file."
        # We don't want exceptions here.
        if os.access(dump_file+".gz", os.F_OK):
            os.remove(dump_file+".gz")
        sys.exit(1)

    print "#* Dumped experiment '%s' to '%s'." % (exp_name, dump_file+".gz")
    return

if __name__ == "__main__":
    global dump_file
    dump_file = None
    
    run_mode = getenv("PB_RUNMODE")
    if run_mode == "debug":
        main()
    else:
        try:
            main()
        except KeyboardInterrupt:
            print "#* User aborted dump operation. No dump file was generated."
            if dump_file is not None:
                # We don't want exceptions here.
                if os.access(dump_file, os.F_OK):
                    os.remove(dump_file)
        except StandardError, error_msg:
            print "#* ERROR:", error_msg
            sys.exit(1)
    sys.exit(0)
