SAP_UDF_REGISTRY = {
    # Item Groups Table
    "OITB": {
        "U_Brand": "Brand: Identifies the brand of the product.",
        "U_GProp": "Category / Main Category: Third level of the product hierarchy. This field should be treated as the primary Category or Main Category. Includes abbreviations like HA (Home Appliances) and SA (Small Appliances).",
        "U_SB": "Sub Brand: Represents the secondary brand, sub-brand, or specific brand line associated with the product."
    },
    
    # Item Master Data Table
    "OITM": {
        "U_GC": "Group Category: First level of the product hierarchy. Represents the broadest product grouping. ONLY use this if the user explicitly asks for 'First Level' or 'Group Category'. DO NOT use for general category searches.",
        "U_HC": "Head Category: Second level of the product hierarchy. Provides a more specific classification under U_GC. ONLY use this if the user explicitly asks for 'Second Level' or 'Sub Category'. DO NOT use for general category searches.",
        "U_SubCategory": "Sub Category: Final level of the product hierarchy. Provides the most specific product classification.",
        "U_SIZE": "Size / Capacity: Represents the final physical size or capacity of the product, such as 32 inches, 55 inches, 200 litres, etc.",
        "U_COLOR": "Color: Represents the color of the product when applicable. For products where color is not relevant, this field may be blank or NA.",
        "U_Series": "Product Series / Model Line: Represents the specific family or series of the product. Use this field when the user asks for 'A Series', 'F Series', 'M Series', 'Galaxy', etc.",
        "U_Festive": "Festive Support: Indicates if the item is associated with a specific festive campaign, offer, or festive support.",
        "U_Pincode": "Required Pincode: Represents the required postal pincode for the item.",
        "U_TotalMargin": "Total Margin: Represents the total margin mapped to the item.",
        "U_PriceList": "Price List: Represents the specific price list for the item."
    },
    # A/R Invoice Lines Table
    "INV1": {
        "U_MovementType": "Movement Type: Represents the specific inventory movement type for the invoice line item.",
        "U_MRP": "MRP / Maximum Retail Price: Represents the maximum retail price mapped to the invoice line item."
    },
    "OPCH": {
        "U_Vendor": "Vendor Code: Represents the vendor code.",
        "U_VenName": "Vendor Name: Represents the name of the vendor.",
        "U_City": "City: Represents the city of the transaction.",
        "U_CardName": "New Customer Name: Represents the new customer name associated with the invoice.",
        "U_Series": "Series: Represents the transaction series.",
        "U_U_mobno": "Mobile Number: Represents the mobile number.",
        "U_MOD": "Mode of Transportation: Represents how the goods were transported.",
        "U_SpeDis": "Special Discount: Represents any special discount applied to the document.",
        "U_RecAmount": "Received Amount: Represents the total received amount."
    }
   
}