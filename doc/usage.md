## How To Use DEPAL within Digital Earth Pacific MS Planetary Computer

### Intial Setup *(only needs to be done once)*


1. Login to https://dep-staging.westeurope.cloudapp.azure.com/ with your provisioned access.
2. Open terminal by clicking File, New -> Terminal
3. Clone the DEPAL library repository by copying and pasting the following command:
   `git clone https://github.com/digitalearthpacific/depal`
4. Change into the depal folder by running in the terminal:
   `cd depal`
5. Create a new notebook by clicking FIle, New -> Notebook
6. Copy and paste the following into the first cell to start using DEPAL:
   
   ```
   import depal as dep
   import warnings
   warnings.filterwarnings('ignore')
   ```
