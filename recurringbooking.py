from olpy.flight import Flight
import csv
import yaml
import sqlalchemy
import pandas as pd
from io import StringIO
import numpy as np
import re

file = '/Users/nicholas/local/mappers/middlesexmapper.yaml'
with open(file) as stream:
    mapper = yaml.safe_load(stream)
    creds = mapper['hikariConfigs']['middlesex']

pattern = re.compile("(org\w+)")

db_name = pattern.search(creds['jdbcUrl']).group(1) 
username = creds['username']
password = creds['password']

middlesex_engine = sqlalchemy.create_engine(f'postgresql://{username}:{password}@atlas.openlattice.com:30001/{db_name}',connect_args={'sslmode':'require'})

print('Engine created')

booking_query = """select * from booking where "COMDATE" >= current_date - interval '1 week';"""
booking_df=pd.read_sql_query(booking_query, middlesex_engine)

print('Query completed')

booking_df['DATASOURCE'] = "Middlesex County Jail"
booking_df.loc[:,'SENTENCE_PK'] = booking_df['PCP'].astype(str) + booking_df['COMDATE'].astype(str)

# Make a flight object from current yaml
fl = Flight()
fl.deserialize('/Users/nicholas/repos/Middlesex/msobooking.yaml')
middlesex_booking_fd = fl.schema
flight_cols = [col for col in fl.get_all_columns() if col[:4] != "assn" if col not in ['ROLE', 'DNA_ROLE_DESCRIPTION', 'COM_ROLE_DESCRIPTION', 'REL_ROLE_DESCRIPTION']]

# Create a dataframe which is a subset of the original table from columns included in the flight
clean_booking = booking_df[flight_cols]

# Strip all whitespace from object (string) columns, and remove all blank strings ('')
clean_booking = clean_booking.apply(lambda x: x.str.strip() if x.dtype == "object" else x)
clean_booking.replace('', np.nan, inplace=True)

# Make float columns to int to fit with the desired datatypes on prod
clean_booking.loc[:,'SERVED'] = clean_booking['SERVED'].astype('Int64')
clean_booking.loc[:,'AGE'] = clean_booking['AGE'].astype('Int64')
clean_booking.loc[:,'SYSID'] = booking_df['SYSID'].astype('Int64')
clean_booking.loc[:,'SENTENCED_AS_ADULT'] = clean_booking['SENTENCED_AS_ADULT'].map({'Y': 1, 'N': 0}).astype('Int64')



# Standardize Race, Sex, Ethnicity
clean_booking['RACE'] = clean_booking['RACE'].map({"A ":"Asian", "AM":"Native American", "AS": "Asian", "B ": "Black", "W ": "White"}).fillna("Unknown")
clean_booking['HISPANIC'] = clean_booking['HISPANIC'].map({"N":"Non-Hispanic", "Y":"Hispanic"}).fillna("Unknown")
clean_booking['SEX'] = clean_booking['SEX'].map({"M":"Male", "m":"Male", "F":"Female"}).fillna("Unknown")

# Make names Title case
for col in ['FIRSTNAM', 'MIDDLE', 'LASTNAME']:
    clean_booking.loc[:,col] = clean_booking[col].str.title()


# Officer Roles
clean_booking.loc[clean_booking['IDOFF'].notna(), 'ROLE'] = 'Officer'

clean_booking.loc[clean_booking['DNA_SAMPLE_OFFICER'].notna(), 'ROLE'] = 'Officer'
clean_booking.loc[clean_booking['DNA_SAMPLE_OFFICER'].notna(), 'DNA_ROLE_DESCRIPTION'] = 'DNA'

clean_booking.loc[clean_booking['COMOFF'].notna(), 'ROLE'] = 'Officer'
clean_booking.loc[clean_booking['COMOFF'].notna(), 'COM_ROLE_DESCRIPTION'] = 'Committing'

clean_booking.loc[clean_booking['RELOFF'].notna(), 'ROLE'] = 'Officer'
clean_booking.loc[clean_booking['RELOFF'].notna(), 'REL_ROLE_DESCRIPTION'] = 'Releasing'


date_columns = ['BIRTH']

for col in date_columns:
    clean_booking[col] = clean_booking[col].dt.strftime('%Y-%m-%d')
    clean_booking.loc[clean_booking[col] == 'NaT', col] = np.nan


datetime_columns = [k for (k,v) in clean_booking.dtypes.items() if v.type == np.datetime64]
for col in datetime_columns:
    clean_booking[col] = pd.to_datetime(clean_booking[col], errors='coerce').dt.tz_localize("America/New_York")

    
# Make a new column for sentence PK
clean_booking['SENTENCE_PK'] = clean_booking['PCP'].astype(str) + clean_booking['COMDATE'].astype(str)

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

make_assn_cols(clean_booking, middlesex_booking_fd)


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

clean_booking.to_sql("zzz_clean_booking_1w", if_exists='replace', middlesex_engine, method=psql_insert_copy)
