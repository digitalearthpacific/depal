## How To Use DEPAL within Digital Earth Pacific MS Planetary Computer

### Initial Setup *(only needs to be done once)*

1. Login to https://dep-staging.westeurope.cloudapp.azure.com/ with your provisioned access.
2. Open terminal by choosing on the menu: File, New -> Terminal
3. Clone the DEPAL library repository by copying and pasting the following command:
   
   `git clone https://github.com/digitalearthpacific/depal`
5. Change into the depal folder by running in the terminal:

   `cd depal`
6. Create a new notebook by clicking File, New -> Notebook
7. Copy and paste the following into the first cell to start using DEPAL:
   
   ```
   import depal as dep
   import warnings
   warnings.filterwarnings('ignore')
   ```
8. Refer to https://github.com/digitalearthpacific/depal/blob/main/doc/depal.pdf for DEPAL API and Functions.

### Updating

DEPAL library will be continuosly updated and improved. To ensure that you are always working with the latest version, update the library by:

1. Open terminal by choosing on the menu: File, New -> Terminal
2. Change into the depal folder by running in the terminal:

   `cd depal`
3. Get latest changes by running the following in the terminal:

    `git pull`
