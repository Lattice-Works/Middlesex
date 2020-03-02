import sqlalchemy
import pandas as pd
import numpy as np
import yaml
from flighttools import flight

file = "***"
with open(file) as stream:
    mapper = yaml.safe_load(stream)
    creds = mapper['hikariConfigs']['middlesex']

db_name = creds['dbname']
usr_name = creds['username']
db_password = creds['password']

middlesex_engine = sqlalchemy.create_engine(f'postgresql://{usr_name}:{db_password}@atlas.openlattice.com:30001/{db_name}',connect_args={'sslmode':'require'})

booking_query = "select * from booking;"
booking_df=pd.read_sql_query(booking_query, middlesex_engine)

# Make a flight object from current yaml
fl = flight.Flight()
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

# Select columns which are np.datetime64 and make  them into dates (dt.floor('d'))
date_columns = [k for (k,v) in clean_booking.dtypes.items() if v.type == np.datetime64]

for col in date_columns:
    clean_booking[col] = clean_booking[col].dt.floor('d')


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

# Take a sample and make a csv for sample integrations
clean_booking_sample = clean_booking.sample(1000)

clean_booking_sample.to_csv('cleanbookingsample.csv')