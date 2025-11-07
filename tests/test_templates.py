def test_id_rsa_template_contains_marker():
    with open("seeder/templates/id_rsa.template","r") as f:
        txt = f.read()
    assert "FAKE_PRIVATE_KEY_PLACEHOLDER" in txt
