#! /usr/bin/env python

"""New admin tool.

connect dbname=.. host=.. service=.. queue=..;
connect queue=..;
connect queue=.. node=..;

install pgq;
install londiste;

---------------------
show all queues | consumers;

show queue ..;
show consumer ..;
show batch events <>;
show batch info <>;

show_queue_info <q>;
show_queue_stats <q>;
show_consumer_batch <cons>;
show_batch_info <bid>;
show_batch_events <bid> [ev_id];

---------------------
alter queue <qname> set param = , ...;

create queue <qname>; // db
register consumer foo;
unregister consumer foo
drop queue <q>;

------------
create node <foo>; // 
create node <qname>.<foo>; // 

add location <node> <loc>; // db, queue
----------------

"""

__version__ = '0.1'

cmdline_usage = '''\
Usage: newadm [switches]

Initial connection options:
    -h host
    -p port
    -U user
    -d dbname

Command options:
    -c cmd_string
    -f execfile

General options:
    --help
    --version
'''

import sys, os, readline, skytools, getopt, re

script = None

IGNORE_HOSTS = {
    'ip6-allhosts': 1,
    'ip6-allnodes': 1,
    'ip6-allrouters': 1,
    #'ip6-localhost': 1,
    'ip6-localnet': 1,
    'ip6-loopback': 1,
    'ip6-mcastprefix': 1,
}

def unquote_any(self, s):
    if s:
        c = s[0]
        if c == "'":
            s = skytools.unquote_literal(c, stdstr = True)
        elif c == '"':
            s = skytools.unquote_ident(c)
        # extquote?
    return s

class Node:
    def __init__(self, **kwargs):
        self.name = kwargs.get('name')
    def get_next(self, typ, word, params):
        return None
    def get_completions(self, params):
        return []

class Proxy(Node):
    def set_real(self, node):
        self.get_next = node.get_next
        self.get_completions = node.get_completions

class WList(Node):
    c_append = ' '
    def __init__(self, *args, **kwargs):
        Node.__init__(self, **kwargs)
        self.wlist = args

    def get_wlist(self):
        return self.wlist

    def get_next(self, typ, word, params):
        cw = word.lower()
        for w in self.get_wlist():
            if w.word == cw:
                if self.name:
                    params[self.name] = cw
                return w.next
        return None

    def get_completions(self, params):
        wlist = self.get_wlist()
        comp_list = []
        for w in wlist:
            comp_list += w.get_completions(params)
        return comp_list

class DynList(Node):
    tk_type = ('ident',)
    c_append = ' '
    def __init__(self, next, **kwargs):
        Node.__init__(self, **kwargs)
        self.next = next

    def get_wlist(self):
        return []

    def get_next(self, typ, word, params):
        if typ not in self.tk_type:
            return None
        if self.name:
            params[self.name] = word
        return self.next

    def get_completions(self, params):
        wlist = self.get_wlist()
        comp_list = [w + self.c_append for w in wlist]
        return comp_list

class Queue(DynList):
    def get_wlist(self):
        return script.get_queue_list()

class DBNode(DynList):
    def get_wlist(self):
        return script.get_node_list()

class Database(DynList):
    def get_wlist(self):
        return script.get_database_list()

class Host(DynList):
    def get_wlist(self):
        return script.get_host_list()

class User(DynList):
    def get_wlist(self):
        return script.get_user_list()

class Port(DynList):
    tk_type = ("num",)
    def get_wlist(self):
        return ['5432', '6432']

class Word(Node):
    tk_type = ("ident",)
    c_append = ' '
    def __init__(self, word, next, **kwargs):
        Node.__init__(self, **kwargs)
        self.word = word
        self.next = next
    def get_next(self, typ, word, params):
        if typ in self.tk_type and word == self.word:
            return self.next
        return None
    def get_completions(self, params):
        return [self.word + self.c_append]

class SWord(Word):
    c_append = '='

class Symbol(Word):
    tk_type = ("sym",)
    c_append = ''

class EQ(Symbol):
    def __init__(self, next):
        Symbol.__init__(self, '=', next)

class Value(Node):
    tk_type = ("str", "num", "ident")
    def __init__(self, next, **kwargs):
        Node.__init__(self, **kwargs)
        self.next = next
    def get_next(self, typ, word, params):
        if typ not in self.tk_type:
            return None
        if self.name:
            params[self.name] = word
        return self.next
    def get_completions(self, params):
        return []

##
##  Now describe the syntax.
##

top_level = Proxy()

w_done = Symbol(';', top_level)

eq_val = Symbol('=', Value(w_done, name = 'value'))

w_connect = Proxy()
w_connect.set_real(
    WList(
        SWord('dbname', EQ(Database(w_connect, name = 'dbname'))),
        SWord('host', EQ(Host(w_connect, name = 'host'))),
        SWord('port', EQ(Port(w_connect, name = 'port'))),
        SWord('user', EQ(User(w_connect, name = 'user'))),
        SWord('password', EQ(Value(w_connect, name = 'password'))),
        SWord('queue', EQ(Queue(w_connect, name = 'queue'))),
        SWord('node', EQ(DBNode(w_connect, name = 'node'))),
        w_done))

w_set = WList(
    SWord('queue', EQ(Queue(w_done, name = 'value'))),
    SWord('consumer', EQ(Value(w_done, name = 'value'))),
    name = "param")

w_show = WList(
    Word('queues', w_done),
    Word('databases', w_done),
    Word('consumers', w_done),
    Word('stats', w_done),
    name = "show")

w_install = WList(
    Word('pgq', w_done),
    Word('londiste', w_done),
    name = 'module')

w_create = Word('queue', Value(w_done, name = 'queue'))

w_top = WList(
    Word('connect', w_connect),
    Word('create', w_create),
    Word('install', w_install),
    Word('set', w_set),
    Word('show', w_show),
    name = "cmd")

top_level.set_real(w_top)

##
## Main class for keeping the state.
##

class AdminConsole:
    cur_queue = None
    cur_database = None

    cmd_file = None
    cmd_str = None

    comp_cache = {
        'comp_pfx': None,
        'comp_list': None,
        'queue_list': None,
        'database_list': None,
        'consumer_list': None,
        'host_list': None,
        'user_list': None,
    }
    db = None

    rc_hosts = re.compile('\s+')
    def get_queue_list(self):
        q = "select queue_name from pgq.queue order by 1"
        return self._ccache('queue_list', q, 'pgq')

    def get_database_list(self):
        q = "select datname from pg_catalog.pg_database order by 1"
        return self._ccache('database_list', q)

    def get_user_list(self):
        q = "select usename from pg_catalog.pg_user order by 1"
        return self._ccache('user_list', q)

    def get_consumer_list(self):
        q = "select co_name from pgq.consumer order by 1"
        return self._ccache('consumer_list', q, 'pgq')

    def get_node_list(self):
        q = "select distinct node_name from pgq_node.node_location order by 1"
        return self._ccache('node_list', q, 'pgq_node')

    def _ccache(self, cname, q, req_schema = None):
        if not self.db:
            return []

        # check if schema exists
        if req_schema:
            k = "schema_exists_%s" % req_schema
            ok = self.comp_cache.get(k)
            if ok is None:
                curs = self.db.cursor()
                ok = skytools.exists_schema(curs, req_schema)
                self.comp_cache[k] = ok
            if not ok:
                return []

        # actual completion
        clist = self.comp_cache.get(cname)
        if clist is None:
            curs = self.db.cursor()
            curs.execute(q)
            clist = [r[0] for r in curs.fetchall()]
            self.comp_cache[cname] = clist
        return clist

    def get_host_list(self):
        clist = self.comp_cache.get('host_list')
        if clist is None:
            try:
                f = open('/etc/hosts', 'r')
                clist = []
                while 1:
                    ln = f.readline()
                    if not ln:
                        break
                    ln = ln.strip()
                    if ln == '' or ln[0] == '#':
                        continue
                    lst = self.rc_hosts.split(ln)
                    for h in lst[1:]:
                        if h not in IGNORE_HOSTS:
                            clist.append(h)
                clist.sort()
                self.comp_cache['host_list'] = clist
            except:
                clist = []
        return clist

    def parse_cmdline(self, argv):
        switches = "c:h:p:d:U:f:"
        lswitches = ['help', 'version']
        try:
            opts, args = getopt.getopt(argv, switches, lswitches)
        except getopt.GetoptError, ex:
            print str(ex)
            print "Use --help to see command line options"
            sys.exit(1)

        cstr_map = {
            'dbname': None,
            'host': None,
            'port': None,
            'user': None,
            'password': None,
        }
        cmd_file = cmd_str = None
        for o, a in opts:
            if o == "--help":
                print cmdline_usage
                sys.exit(0)
            elif o == "--version":
                print "newadm version %s" % __version__
                sys.exit(0)
            elif o == "-h":
                cstr_map['host'] = a
            elif o == "-p":
                cstr_map['port'] = a
            elif o == "-d":
                cstr_map['dbname'] = a
            elif o == "-U":
                cstr_map['user'] = a
            elif o == "-c":
                self.cmd_str = a
            elif o == "-f":
                self.cmd_file = a

        cstr_list = []
        for k, v in cstr_map.items():
            if v is not None:
                cstr_list.append("%s=%s" % (k, v))
        if len(args) == 1:
            a = args[0]
            if a.find('=') >= 0:
                cstr_list.append(a)
            else:
                cstr_list.append("dbname=%s" % a)
        elif len(args) > 1:
            print "too many arguments, use --help to see syntax"
            sys.exit(1)

        self.initial_connstr = " ".join(cstr_list)

    def db_connect(self, connstr):
        db = skytools.connect_database(connstr)
        db.set_isolation_level(0) # autocommit

        q = "select current_database(), current_setting('server_version')"
        curs = db.cursor()
        curs.execute(q)
        res = curs.fetchone()
        self.cur_database = res[0]
        return db

        #print res
        #print dir(self.db)
        #print dir(self.db.cursor())
        #print self.db.status
        #print "connected to", repr(self.initial_connstr)


    def run(self, argv):
        self.parse_cmdline(argv)

        if self.cmd_file is not None and self.cmd_str is not None:
            print "cannot handle -c and -f together"
            sys.exit(1)

        cmd_str = self.cmd_str
        if self.cmd_file:
            cmd_str = open(self.cmd_file, "r").read()

        self.db = self.db_connect(self.initial_connstr)

        if cmd_str:
            self.exec_string(cmd_str)
        else:
            self.main_loop()

    def main_loop(self):
        readline.parse_and_bind('tab: complete')
        readline.set_completer(self.rl_completer_safe)
        #print 'delims: ', repr(readline.get_completer_delims())
        hist_file = os.path.expanduser("~/.newadm_history")
        try:
            readline.read_history_file(hist_file)
        except IOError:
            pass

        while 1:
            try:
                ln = self.line_input()
                #print 'line:', repr(ln)
                self.exec_string(ln)
            except KeyboardInterrupt:
                print
            except EOFError:
                print
                break
            self.reset_comp_cache()
        readline.write_history_file(hist_file)

    def rl_completer(self, curword, state):
        curline = readline.get_line_buffer()
        start = readline.get_begidx()
        end = readline.get_endidx()

        pfx = curline[:start]
        sglist = self.find_suggestions(pfx, curword)
        if state < len(sglist):
            return sglist[state]
        return None

    def rl_completer_safe(self, curword, state):
        try:
            return self.rl_completer(curword, state)
        except BaseException, det:
            print 'got some error', str(det)

    def line_input(self):
        qname = "(noqueue)"
        if self.cur_queue:
            qname = self.cur_queue
        p = "%s@%s> " % (qname, self.cur_database)
        return raw_input(p)

    def sql_words(self, sql):
        return skytools.sql_tokenizer(sql,
                standard_quoting = True,
                ignore_whitespace = True)

    def reset_comp_cache(self):
        self.comp_cache = {}

    def find_suggestions_real(self, pfx, params):
        # find level
        node = top_level
        for typ, w in self.sql_words(pfx):
            w = w.lower()
            node = node.get_next(typ, w, params)
            if not node:
                break

        # find possible matches
        if node:
            return node.get_completions(params)
        else:
            return []

    def find_suggestions(self, pfx, curword, params = {}):
        c_pfx = self.comp_cache.get('comp_pfx')
        c_list = self.comp_cache.get('comp_list', [])
        if c_pfx != pfx:
            c_list = self.find_suggestions_real(pfx, params)
            self.comp_cache['comp_pfx'] = pfx
            self.comp_cache['comp_list'] = c_list

        wlen = len(curword)
        res = []
        for cword in c_list:
            if curword == cword[:wlen]:
                res.append(cword)
        return res

    def exec_string(self, ln, eof = False):
        node = top_level
        params = {}
        for typ, w in self.sql_words(ln):
            w = w.lower()
            #print repr(typ), repr(w)
            if typ == 'error':
                print 'syntax error:', repr(ln)
                return
            node = node.get_next(typ, w, params)
            if not node:
                print "syntax error:", repr(ln)
                return
            if node == top_level:
                self.exec_params(params)
                params = {}
        if eof:
            if params:
                self.exec_params(params)
        elif node != top_level:
            print "multi-line commands not supported:", repr(ln)

    def exec_params(self, params):
        cmd = params.get('cmd')
        if not cmd:
            print 'parse error: no command found'
            return
        #print 'RUN', repr(params)
        fn = getattr(self, 'cmd_' + cmd, self.bad_cmd)
        fn(params)

    def bad_cmd(self, params):
        print 'unimplemented command'

    def cmd_connect(self, params):
        qname = params.get('queue')
        if not qname:
            qname = self.cur_queue
        if 'node' in params and not qname:
            print 'node= needs a queue also'
            return

        # load raw connection params
        cdata = []
        for k in ('dbname', 'host', 'port', 'user', 'password'):
            if k in params:
                arg = "%s=%s" % (k, params[k])
                cdata.append(arg)

        # raw connect
        if cdata:
            if 'node' in params:
                print 'node= cannot be used together with raw params'
                return
            cstr = " ".join(cdata)
            self.db = self.db_connect(cstr)

        # connect to node
        if 'node' in params:
            curs = self.db.cursor()
            q = "select node_location from pgq_node.get_queue_locations(%s)"\
                " where node_name = %s"
            curs.execute(q, [qname, params['node']])
            res = curs.fetchall()
            if len(res) == 0:
                print "node not found"
                return
            cstr = res[0]['node_location']
            self.db = self.db_connect(cstr)

        # set default queue
        if 'queue' in params:
            self.cur_queue = qname
            print 'queue=', qname

    def cmd_install(self, params):
        pgq_objs = [
            skytools.DBLanguage("plpgsql"),
            skytools.DBFunction("txid_current_snapshot", 0, sql_file="txid.sql"),
            skytools.DBSchema("pgq", sql_file="pgq.sql"),
            skytools.DBSchema("pgq_ext", sql_file="pgq_ext.sql"),
            skytools.DBSchema("pgq_node", sql_file="pgq_node.sql"),
        ]
        londiste_objs = pgq_objs + [
            skytools.DBSchema("londiste", sql_file="londiste.sql"),
        ]
        mod_map = {
            'londiste': londiste_objs,
            'pgq': pgq_objs,
        }
        mod_name = params['module']
        objs = mod_map[mod_name]
        if not self.db:
            print "no db?"
            return
        curs = self.db.cursor()
        skytools.db_install(curs, objs, None)
        print "%s installed" % mod_name

def main():
    global script

    script = AdminConsole()
    script.run(sys.argv[1:])

def test(pfx, curword):
    global script
    params = {}
    script = AdminConsole()
    sgs = script.find_suggestions(pfx, curword, params)
    #print repr(pfx), repr(curword), repr(sgs), repr(params)

def sgtest():
    global script
    script = AdminConsole()
    test('', '')
    test('', 'se')
    test('', 'cr')
    test('set ', '')
    test('set ', 'q')
    test('set queue = blah;', '')
    test('set queue = ', '')

    script.exec_string('create queue foo;')
    script.exec_string('create queue "foo";')
    script.exec_string('create queue \'foo\';')

if __name__ == '__main__':
    #sgtest()
    main()
