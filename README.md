# ISO 20022 Structured Address (Libpostal) Converter
ISO 20022 is about data, structured data which, when populated, can bring significant benefits.
One of the main data elements used in payments and cash management, is the humble address - of
the debtor (payer), the creditor (payee) or any other party or bank involved.
Many systems, applications, reference data sources such as customer records, only capture
unstructured addresses, i.e. adress line 1, address line 2, possibly town and country etc.
Many major payments schemes and infrastructures, having migrated to ISO 20022 are now starting to 
require the use of a strucutred address, i.e. Building Number, Building Name, Street Name, Postcode,
Town Name (mandatory) and Country Code (also mandatory).  There are 14 individual address elements.
The challenge is converting unstructured addresses to structured addresses.  This code addresses
(pun intended) this problem, proving an effective solution using parsing, libpostal (ML) and optionally, 
geocoders; aiming to prove there is no need for generative AI ✨ (but it may help as a last resort!)

## Input:
Text file of one or more addresses (one per line)

## Return/Output:
csv file of the original address, the parsed elements, the converted xml for a structured or hybrid address,
xsd validation result, any xsd validation errors, flags to show if the converted address has undergone
character replacement or truncation.  If geo-enrichment is pemitted, flags to show if 
town or country has been enriched. 

## Summary:
Reads a file of one or more addresses and converts to ISO 20022 PostalAddress24 stuctured address(es).
Important to note that libpostal does not enrich the address, only parses into individual elements which
can then be mapped to the PostalAddress24 elements.  If the source unstructured address is of insufficient 
quality such as missing a discernable town/city or country, the libpostal parsed address will also be missing
these fields and therefore it will be unlikely a valid PostalAddress24, either strucutred or hybrid,
can be produced.  To resolve, the deficient address should be corrected at source, however, it may be possible
to use geocoders to enrich the missing address elements, if the source address has sufficient detail.  
The *allow_geo_enrichment* option is for this purpose but it should be used with caution to avoid incorrect 
data and regulatory issues.  The geocoder enrichment, if used, should be upgraded to a production feature,
as this code only uses the open-source rate-limited APIs.  The call out to a geocoder could be a call to
an AI service using an LLM.  Note, it is also possible the unstructured address does have a town
and country but is not parsed correctly by Libpostal (it is a model trained on address data so does
expect it in a certain order).

Each address is normalised after the libpostal parsing (and optional geo-enrichment), to conform
to the CBPR+ extended character set and each element truncated, if neccessary, to fit the permitted
field lengths.  Truncation will always be indicated with an appended + symbol at the end of the field.
Any address that is altered in these ways will be flagged as *is_replaced=True* and/or *is_truncated=True*
Any address that has been ge0-enrich will be flagged as *city_enriched=True* and/or *country_enriched=True*.

Finally, the converted address is validated against the loaded xsds, either structured or hybrid.

Optionally, the following can be enabled:

- *allow_hybrid*:  default is False.  If set to True, allows conversion to a hybrid address if any strucutred address element exceeds the max length and would be truncated.  Essentially, it minimises truncation of structured address elements.  Hybrid address is a limited-lifespan option, hence can be disabled to only allow structured address conversion once the usage guidelines forid hybrid addresses.

- *allow_geo_enrichment*:  default is False.  PostalAddress24 (structured and hybrid) requires both a Town Name and Country Code. 
If these are not present, enabling this option will invoke geocoders to attempt to enrich the address with the country code and nearest town.

## Installation
This python application is using python 3.12 and libpostal (on WSL) 

Install the packages in the requirements.txt
```sh
pip install -r requirements.txt
```

Libpostal should be installed and configured on WSL. A simple guide to WSL and Libpostal is:

[Affinis Installation Guide for WSL and Libpostal](https://affinis.co.uk/libpostal-installation-and-configuration-on-wsl/)

Github for Libpostal is:

[Github Openvenues Libpostal](https://github.com/openvenues/libpostal)

Once installed, upgrade to the Senzing model.

[Github Senzing Libpostal](https://github.com/Senzing/libpostal-data)

## Configuration

### Config.py.template
The code includes a template config file.  Rename this from configy.py.template to config.py and edit the 
configuration as required.

### Libpostal Data Directory
This python application needs to know the libpostal data directory.
The following code is found in the *libpostal_config.py* file.  Edit the location to point to your
libpostal data directory

```sh
# Edit this to your libpostal data directory, if not this
os.environ['LIBPOSTAL_DATA_DIR'] = '/usr/local/share/libpostal'
```

## Logging
This application will log events in a file called *application.log* found in the same location as the output csv file.  The *log_config.py* can be edited to adjust the logging.  It is currently set to max log file size of 15Mb and when exceeded, a new log file is created, up to a maxiumum of 10 log files.  Be aware that some address data may be written to the log file, such as address data that will be truncated.  

## Use of Gecoders
Banks, payment service providers and other money movers, have several regulatory obligation, such as the Funds Transer Regulations and a plethora of sanctions, AML and KYC related checks.  Using a geocoder to enrich what is likely to be an otherwise inadequate address, one that could not readily identify the location of the party involved in the payment, may conflict with the requirement to have undertaken due diligence and comply with the various regulations.  If the address is too sparsely populated to produce a valid ISO 20022 structured address, the priority should be to make improvements/corrections at source, then retry.  Geocoders should only be used where source correction either cannot be completed or has no effect - it should be considered a fallback and best reserved for the creditor address, never the debtor address (i.e. your customer, where KYC should be the path to data improvement).

## Author and Contact
Dominic Digby
Contact me via LinkedIn