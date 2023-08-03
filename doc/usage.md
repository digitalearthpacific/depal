# How To Use DEPAL within Digital Earth Pacific MS Planetary Computer

## Initial Setup *(only needs to be done once)*

1. Login to https://dep-staging.westeurope.cloudapp.azure.com/ with your provisioned access.
2. Open terminal by choosing on the menu: File, New -> Terminal
3. Clone the DEPAL library repository by copying and pasting the following command:

   `git clone https://github.com/digitalearthpacific/depal`
4. Change into the depal folder by running in the terminal:

   `cd depal`
5. Create a new notebook by clicking File, New -> Notebook
6. Copy and paste the following into the first cell to start using DEPAL:

   ``` python
      import depal as dep
      import warnings
      warnings.filterwarnings('ignore')
      dep.init()
   ```

7. Ensure that your notebook ends with `dep.cleanup()` on it's last cell to ensure all resources are relesed.
8. **####** Alternatively, right click on *template.ipynb* and select duplicate to start working on a new notebook with the defaults above already in place. **####**  
9. Refer to [depal.pdf](https://github.com/digitalearthpacific/depal/blob/main/doc/depal.pdf) for DEPAL API and Functions.

### Updating

DEPAL library will be continuosly updated and improved. To ensure that you are always working with the latest version, update the library by:

1. Open terminal by choosing on the menu: File, New -> Terminal
2. Change into the depal folder by running in the terminal:

   `cd depal`
3. Get latest changes by running the following in the terminal:

    `git pull`

### Scaling Up

By default, DEPAL will default to image processing output of **100m2**. To change to a higher resolution output, at the begining of your notebook, change from:

`dep.init()`

to eg:

`dep.init("remote", resolution=10)` for 10m/2 output

For larger areas of interest, you may need to scale up the number workers by, eg:

`dep.init("remote", maxWorkers=24, resolution=10, )`
