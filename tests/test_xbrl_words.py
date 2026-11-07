from filinglens.xbrl import _words


def test_concept_and_label_words_overlap():
    concept = _words("PaymentsToAcquirePropertyPlantAndEquipment")
    label = _words("Purchases of property, plant and equipment (PP&E)")
    assert {"property", "plant", "equipment"} <= concept & label


def test_stopwords_dropped():
    assert "total" not in _words("Total current liabilities") and "liabilitie" in _words("LiabilitiesCurrent")


def test_synonyms_bridge_label_and_concept_vocabulary():
    assert _words("Net sales") & _words("RevenueFromContractWithCustomerExcludingAssessedTax")
    assert _words("Total inventories") & _words("InventoryNet")
