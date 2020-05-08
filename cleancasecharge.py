import sqlalchemy
import re
import csv
from io import StringIO
import pandas as pd
import numpy as np
import yaml
from olpy.flight import Flight

file = "/Users/nicholas/local/mappers/middlesexmapper.yaml"
with open(file) as stream:
    mapper = yaml.safe_load(stream)
    creds = mapper['hikariConfigs']['middlesex']

pattern = re.compile("(org\w+)")

db_name = pattern.search(creds['jdbcUrl']).group(1)
usr_name = creds['username']
db_password = creds['password']

middlesex_engine = sqlalchemy.create_engine(f'postgresql://{usr_name}:{db_password}@atlas.openlattice.com:30001/{db_name}',connect_args={'sslmode':'require'})

# booking query needed for join on SYSID to get PCP (person id)
booking_query = 'select "SYSID", "PCP" from booking;'
booking_df=pd.read_sql_query(booking_query, middlesex_engine)

print('Engine created')

case_charge_query = "select * from case_charge;"
case_charge_df=pd.read_sql_query(case_charge_query, middlesex_engine)

print('Query completed')

# Make a flight object from current yaml
fl2 = Flight()
fl2.deserialize('/Users/nicholas/Clients/Middlesex/msocasecharge.yaml')
middlesex_cc_fd = fl2.schema
cc_flight_cols = list(fl2.get_all_columns())

# Create a dataframe which is a subset of the original table from columns included in the flight
clean_cc = case_charge_df[cc_flight_cols]

# Make OFFENSE_DATE into a datetime and coerce errors (make NaT) since datetime64 only goes to ~2250AD and some values are from 6201AD
clean_cc.loc[:,'OFFENSE_DATE'] = pd.to_datetime(clean_cc['OFFENSE_DATE'], errors = 'coerce')

    
# Strip all whitespace from object (string) columns and remove empty strings ('')
clean_cc = clean_cc.applymap(lambda x: x.str.strip() if type(x) == 'str' else x)
clean_cc.replace('', np.nan, inplace=True)

# Join to booking on SYSID to get PCP (key for inmates)
clean_cc = clean_cc.set_index('SYSID').join(booking_df[['SYSID','PCP']].set_index('SYSID'))
clean_cc = clean_cc.reset_index()


# Prepare dates for SQL
# First select those which need to be dates on backend and add to date_columns
# Then select those which are np.datetime64 in pandas (and possibly others) and localize
date_columns = ['DISPOSITION_DATE']

for col in date_columns:
   clean_cc[col] = clean_cc[col].dt.strftime('%Y-%m-%d')
   clean_cc.loc[clean_cc[col] == 'NaT', col] = np.nan

datetime_columns = [k for (k,v) in clean_cc.dtypes.items() if v.type == np.datetime64]

for col in datetime_columns:
    clean_cc[col] = pd.to_datetime(clean_cc[col], errors='coerce').dt.tz_localize("America/New_York")

clean_cc['CHARGE_ORDER'] = clean_cc['CHARGE_ORDER'].astype('Int64')

# Functions to make association hash and make columns from those
def make_assn_hash(df, col1, col2, name):
    cols = [col1,col2]
    c1nn = df.loc[df[cols].notnull().all(axis=1), col1].astype(str)
    c2nn = df.loc[df[cols].notnull().all(axis=1), col2].astype(str)
    combined_cols =  c1nn + c2nn
    assn_hash = combined_cols.apply(lambda x: hash(x+name))
    return assn_hash

def make_assn_cols(df, fd):
    for k, v in fd['associationDefinitions'].items():
        col_string = f"assn_{k}"
        src, dst = v['src'], v['dst']
        srccol = fd['entityDefinitions'][src]['properties'][0]['column']
        dstcol = fd['entityDefinitions'][dst]['properties'][0]['column']
        df[col_string] = make_assn_hash(df, srccol, dstcol, k)

make_assn_cols(clean_cc, middlesex_cc_fd)


print('Processing finished')

def psql_insert_copy(table, conn, keys, data_iter):
    # gets a DBAPI connection that can provide a cursor
    dbapi_conn = conn.connection
    with dbapi_conn.cursor() as cur:
        s_buf = StringIO()
        writer = csv.writer(s_buf)
        writer.writerows(data_iter)
        s_buf.seek(0)

        columns = ', '.join('"{}"'.format(k) for k in keys)
        if table.schema:
            table_name = '{}.{}'.format(table.schema, table.name)
        else:
            table_name = table.name

        sql = 'COPY {} ({}) FROM STDIN WITH CSV'.format(
            table_name, columns)
        cur.copy_expert(sql=sql, file=s_buf)

clean_cc.to_sql("clean_cc", middlesex_engine, method=psql_insert_copy)
