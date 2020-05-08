import sqlalchemy
import pandas as pd
import numpy as np
import re
from io import StringIO
import csv
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

print('Engine created')

cc_history_query = "select * from case_charge_history;"
cc_history_df=pd.read_sql_query(cc_history_query, middlesex_engine)

print('Query completed')

# Make a flight object from current yaml
fl = Flight()
fl.deserialize('/Users/nicholas/Clients/Middlesex/msocchistory.yaml')
middlesex_cc_hist_fd = fl.schema
cc_hist_cols = list(fl.get_all_columns())

# Create a dataframe which is a subset of the original table from columns included in the flight
clean_cc_hist = cc_history_df[cc_hist_cols]
    
# Strip all whitespace from object (string) columns and remove empty strings ('')
clean_cc_hist = clean_cc_hist.apply(lambda x: x.str.strip() if x.dtype == "object" else x)
clean_cc_hist.replace('', np.nan, inplace=True)

# Prepare dates for SQL
# First select those which need to be dates on backend and add to date_columns
# Then select those which are np.datetime64 in pandas (and possibly others) and localize
date_columns = ['DNA_SAMPLE_DATE','DISPOSITION_DATE']

for col in date_columns:
   clean_cc_hist[col] = clean_cc_hist[col].dt.strftime('%Y-%m-%d')
   clean_cc_hist.loc[clean_cc_hist[col] == 'NaT', col] = np.nan

datetime_columns = [k for (k,v) in clean_cc_hist.dtypes.items() if v.type == np.datetime64    ]

for col in datetime_columns:
    clean_cc_hist[col] = pd.to_datetime(clean_cc_hist[col], errors='coerce').dt.tz_localize("America/New_York")

clean_cc_hist['CHARGE_ORDER'] = clean_cc_hist['CHARGE_ORDER'].astype('Int64')
clean_cc_hist['DNA_SAMPLE_STATUS'] = clean_cc_hist['DNA_SAMPLE_STATUS'].map({'Y': 1, 'N': 0}).astype('Int64')

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

make_assn_cols(clean_cc_hist, middlesex_cc_hist_fd)

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

clean_cc_hist.to_sql("clean_cc_hist", middlesex_engine, method=psql_insert_copy)
