import os
import web
import re
import MySQLdb as mdb
import ConfigParser

urls = (
'/(.*)', 'main'
    )
application = web.application(urls, globals()).wsgifunc()

first_build_number = 1

get_last_build_sql = """
select p.name, p.id,
coalesce(v.maxver_a || '.' || v.maxver_b || '.' || v.maxver_c || '.' || bn.ver_build, 'no build yet') ver from
Project p left outer join
(select lc.project_id, b.maxver_a, b.maxver_b, max(lc.ver_c) maxver_c from LastBuild lc join
(select lb.project_id, a.maxver_a, max(lb.ver_b) maxver_b from LastBuild lb join
(select project_id, max(ver_a) maxver_a from LastBuild group by project_id) as a
on lb.ver_a = a.maxver_a and lb.project_id = a.project_id group by lb.project_id, a.maxver_a) b
on lc.ver_a = b.maxver_a and lc.ver_b = b.maxver_b and lc.project_id = b.project_id
 group by lc.project_id, b.maxver_a, b.maxver_b
) v
on p.id = v.project_id
left outer join LastBuild bn
on v.project_id=bn.project_id and v.maxver_a=bn.ver_a and v.maxver_b=bn.ver_b and v.maxver_c=bn.ver_c
order by upper(p.name) asc
"""

get_build_list_sql = """
select bi.ver_a || '.' || bi.ver_b || '.' || bi.ver_c || '.' || bi.ver_build version,
bi.build_time_utc || ' UTC' build_time_utc_s,
bi.vc_identity, bi.build_tweaks
from Project p join BuildInfo bi on p.id=bi.project_id
where p.name=%s
order by bi.ver_a desc, bi.ver_b desc, bi.ver_c desc, bi.ver_build desc
"""

config = ConfigParser.ConfigParser()
config.read(os.path.dirname(__file__) + '/versionserver.config')

class main:
    def GET(self, name):
        if name == 'generate':
            return self.generate()
        elif name == 'addproject':
            return self.add_project()
        elif name == 'delproject':
            return self.del_project()
        elif name == 'list':
            return self.list()
        else:
            return '<a href="https://github.com/salsita/versionserver">https://github.com/salsita/versionserver</a>'

    def connect_to_db(self):
        conn = mdb.connect('localhost', 'versionserver', config.get('db', 'pass'), 'versionserver')
        conn.cursor().execute("SET sql_mode='PIPES_AS_CONCAT'")
        return conn

    def get_project_id(self, conn, proj_name):
        c = conn.cursor()
        c.execute('select id from Project where name=%s', [proj_name])
        proj_id = c.fetchone()[0]
        return proj_id

    def generate_build_number(self, conn, proj_id, ver_a, ver_b, ver_c):
        c = conn.cursor()
        c.execute("""insert into LastBuild(project_id, ver_a, ver_b, ver_c, ver_build)
                    values (%s, %s, %s, %s, last_insert_id(%s))
                    on duplicate key update ver_build=last_insert_id(ver_build + 1)""",
                    [proj_id, ver_a, ver_b, ver_c, first_build_number])
        c.execute('select last_insert_id()')
        build_number = c.fetchone()[0]
        c.execute("""insert into BuildInfo(project_id, ver_a, ver_b, ver_c, ver_build, build_time_utc)
                    values (%s, %s, %s, %s, %s, UTC_TIMESTAMP)""",
                    [proj_id, ver_a, ver_b, ver_c, build_number])
        return build_number

    def updateBuildInfo(self, conn, proj_id, ver_a, ver_b, ver_c, ver_build, vc_identity, build_tweaks):
        v_condition = 'where project_id=%s and ver_a=%s and ver_b=%s and ver_c=%s and ver_build=%s'
        c = conn.cursor()
        if vc_identity:
            c.execute('update BuildInfo set vc_identity=%s ' + v_condition,
                [vc_identity, proj_id, ver_a, ver_b, ver_c, ver_build])

        if build_tweaks:
            c.execute('update BuildInfo set build_tweaks=%s ' + v_condition,
                [build_tweaks, proj_id, ver_a, ver_b, ver_c, ver_build])

    def generate(self):
        user_input = web.input(vcid=None, buildTweaks=None)
        ver_parse = re.compile('([0-9]+)\\.([0-9]+)\\.([0-9]+)')
        parsed = ver_parse.match(user_input.v)
        ver_a = int(parsed.group(1))
        ver_b = int(parsed.group(2))
        ver_c = int(parsed.group(3))
        proj_name = user_input.project

        conn = self.connect_to_db()
        conn.autocommit(True)
        try:
            proj_id = self.get_project_id(conn, proj_name)
            ver_build = self.generate_build_number(conn, proj_id, ver_a, ver_b, ver_c)
            self.updateBuildInfo(conn, proj_id, ver_a, ver_b, ver_c, ver_build, user_input.vcid, user_input.buildTweaks)
            return str(ver_build)
        finally:
            conn.close()

    def add_project(self):
        user_input = web.input()
        conn = self.connect_to_db()
        c = conn.cursor()
        c.execute('insert into Project(name) values (%s)', [user_input.project])
        proj_id = self.get_project_id(conn, user_input.project)
        conn.commit()
        conn.close()
        return str(proj_id)

    def del_project(self):
        user_input = web.input()
        conn = self.connect_to_db()
        c = conn.cursor()
        c.execute('delete from Project where name=%s', [user_input.project])
        conn.commit()
        conn.close()
        return 'Deleted ' + user_input.project + '.'

    def list(self):
        user_input = web.input(project=None)
        if user_input.project:
            return self.list_project(user_input.project)
        else:
            return self.list_latest()

    def list_project(self, proj_name):
        conn = self.connect_to_db()
        c = conn.cursor()
        c.execute(get_build_list_sql, [proj_name])
        proj_info_table = '<table>'
        proj_info_table += '<tr><th>Version</th><th>Build time</th><th>Changeset identity</th><th>Build tweaks</th></tr>'
        for r in c:
            proj_info_table += '<tr>'
            for rr in r:
                proj_info_table = proj_info_table + '<td>' + str(rr) + '</td>'
            proj_info_table += '</tr>'

        proj_info_table += '</table>'
        return proj_info_table

    def list_project_anchor(self, proj_name):
        return '<a href="list?project=' + proj_name + '">' + proj_name + '</a>'

    def list_latest(self):
        conn = self.connect_to_db()
        c = conn.cursor()
        c.execute(get_last_build_sql)
        proj_info_table = '<table>'
        for r in c:
            proj_info_table = proj_info_table + '<tr><td>' + self.list_project_anchor(r[0]) + '</td><td>' + r[2] + '</td></tr>'

        proj_info_table += '</table>'
        return proj_info_table
