from tools.migrate_postgres import split_sql


def test_split_sql_ignores_semicolons_in_line_comments_and_strings():
    script="""-- migration header; this semicolon is not SQL
CREATE TABLE demo(id INTEGER, note TEXT);
-- another; comment
INSERT INTO demo(id,note) VALUES (1,'a;b');
"""
    statements=split_sql(script)
    assert len(statements)==2
    assert statements[0].startswith("CREATE TABLE demo")
    assert statements[1].startswith("INSERT INTO demo")
    assert "'a;b'" in statements[1]
