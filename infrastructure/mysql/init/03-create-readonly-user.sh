#!/bin/sh
set -eu

MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql \
  --protocol=socket \
  --user=root <<'SQL'
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'text_to_sql_reader'@'%';

GRANT SELECT, SHOW VIEW ON sakila.*
TO 'text_to_sql_reader'@'%';
SQL
