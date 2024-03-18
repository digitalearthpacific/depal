<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor xmlns="http://www.opengis.net/sld" version="1.0.0" xmlns:ogc="http://www.opengis.net/ogc" xmlns:sld="http://www.opengis.net/sld" xmlns:gml="http://www.opengis.net/gml">
  <UserLayer>
    <sld:LayerFeatureConstraints>
      <sld:FeatureTypeConstraint/>
    </sld:LayerFeatureConstraints>
    <sld:UserStyle>
      <sld:Name>fj_lulc_2023</sld:Name>
      <sld:FeatureTypeStyle>
        <sld:Rule>
          <sld:RasterSymbolizer>
            <sld:ChannelSelection>
              <sld:GrayChannel>
                <sld:SourceChannelName>1</sld:SourceChannelName>
              </sld:GrayChannel>
            </sld:ChannelSelection>
            <sld:ColorMap type="values">
              <sld:ColorMapEntry quantity="1" color="#fffb01" label="1"/>
              <sld:ColorMapEntry quantity="2" color="#376a23" label="2"/>
              <sld:ColorMapEntry quantity="3" color="#a4db5d" label="3"/>
              <sld:ColorMapEntry quantity="4" color="#d8260e" label="4"/>
              <sld:ColorMapEntry quantity="5" color="#2fbaa1" label="5"/>
              <sld:ColorMapEntry quantity="6" opacity="0.8" color="#a3f6ff" label="6"/>
              <sld:ColorMapEntry quantity="7" color="#ae8753" label="7"/>
            </sld:ColorMap>
            <sld:VendorOption name="saturation">0.55</sld:VendorOption>
          </sld:RasterSymbolizer>
        </sld:Rule>
      </sld:FeatureTypeStyle>
    </sld:UserStyle>
  </UserLayer>
</StyledLayerDescriptor>
