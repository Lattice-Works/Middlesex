from olpy.flight import Flight
import yaml
import sqlalchemy
import pandas as pd
import numpy as np

file = '/Users/nicholas/local/mappers/middlesexmapper.yaml'
with open(file) as stream:
    mapper = yaml.safe_load(stream)
    creds = mapper['hikariConfigs']['middlesex']

dbname = creds['dbname']
username = creds['username']
password = creds['password']

middlesex_engine = sqlalchemy.create_engine(f'postgresql://{username}:{password}@atlas.openlattice.com:30001/{dbname}',connect_args={'sslmode':'require'})

booking_query = 'select * from booking;'
booking_df=pd.read_sql_query(booking_query, middlesex_engine)

# Make a flight object from current yaml
fl = Flight()
fl.deserialize('/Users/nicholas/Clients/Middlesex/msobooking.yaml')
middlesex_booking_fd = fl.schema
flight_cols = list(fl.get_all_columns())

# Create a dataframe which is a subset of the original table from columns included in the flight
clean_booking = booking_df[flight_cols]

# Strip all whitespace from object (string) columns, and remove all blank strings ('')
clean_booking = clean_booking.apply(lambda x: x.str.strip() if x.dtype == "object" else x)
clean_booking.replace('', np.nan, inplace=True)

# Make float columns to int to fit with the desired datatypes on prod
clean_booking['SERVED'] = clean_booking['SERVED'].astype('Int64')
clean_booking['AGE'] = clean_booking['AGE'].astype('Int64')
clean_booking['SENTENCED_AS_ADULT'] = clean_booking['SENTENCED_AS_ADULT'].map({'Y': 1, 'N': 0}).astype('Int64')

date_columns = ['BIRTH']

for col in date_columns:
    clean_booking[col] = clean_booking[col].dt.strftime('%Y-%m-%d')


datetime_columns = [k for (k,v) in clean_booking.dtypes.items() if v.type == np.datetime64]
for col in datetime_columns:
    clean_booking[col] = pd.to_datetime(clean_booking[col], errors='coerce').dt.tz_localize("America/New_York")

    
# Make a new column for sentence PK
clean_booking['SENTENCE_PK'] = clean_booking['PCP'].astype(str) + clean_booking['COMDATE'].astype(str)

# Functions to make association hash and make columns from those
def make_assn_hash(df, col1, col2, name):
    combined_cols = df[col1].astype(str) + df[col2].astype(str)
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

# Take a sample and make a table on test db for sample integrations

engine = sqlalchemy.create_engine('postgresql://nicholas@localhost:5432/test')
clean_booking.to_sql("clean_booking", engine)
