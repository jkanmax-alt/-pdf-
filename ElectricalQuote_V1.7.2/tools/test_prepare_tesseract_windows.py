"""Regression checks for retaining upstream settings while enabling UTF-8 paths."""
import unittest
import xml.etree.ElementTree as ET

from prepare_tesseract_windows import (
    ASM_V1, ASM_V3, COMPAT_V1, WINDOWS_10_GUID, WINDOWS_SETTINGS_2019,
    utf8_manifest,
)


class UTF8ExecutableManifestTests(unittest.TestCase):
    def test_new_manifest_enables_utf8_and_windows_10(self):
        root = ET.fromstring(utf8_manifest())
        self.assertEqual(root.tag, f'{{{ASM_V1}}}assembly')
        self.assertEqual(root.findtext(
            f'{{{ASM_V3}}}application/{{{ASM_V3}}}windowsSettings/{{{WINDOWS_SETTINGS_2019}}}activeCodePage'), 'UTF-8')
        supported = root.findall(f'{{{COMPAT_V1}}}compatibility/{{{COMPAT_V1}}}application/{{{COMPAT_V1}}}supportedOS')
        self.assertIn(WINDOWS_10_GUID, [node.get('Id') for node in supported])

    def test_original_privilege_dependency_and_display_settings_survive(self):
        original = b'''<?xml version="1.0"?>
        <assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
          <assemblyIdentity name="Upstream.Tesseract" version="5.4.0.0" type="win32"/>
          <dependency><dependentAssembly><assemblyIdentity name="Microsoft.Windows.Common-Controls" version="6.0.0.0"/></dependentAssembly></dependency>
          <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges><requestedExecutionLevel level="asInvoker" uiAccess="false"/></requestedPrivileges></security></trustInfo>
          <application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings><dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true</dpiAware></windowsSettings></application>
          <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1"><application><supportedOS Id="{old-supported-os}"/></application></compatibility>
        </assembly>'''
        root = ET.fromstring(utf8_manifest(original))
        self.assertEqual(root.find(f'{{{ASM_V1}}}assemblyIdentity').get('name'), 'Upstream.Tesseract')
        self.assertIsNotNone(root.find(f'{{{ASM_V1}}}dependency/{{{ASM_V1}}}dependentAssembly/{{{ASM_V1}}}assemblyIdentity'))
        privilege = root.find(f'{{{ASM_V3}}}trustInfo/{{{ASM_V3}}}security/{{{ASM_V3}}}requestedPrivileges/{{{ASM_V3}}}requestedExecutionLevel')
        self.assertEqual(privilege.attrib, {'level': 'asInvoker', 'uiAccess': 'false'})
        self.assertEqual(root.findtext(f'{{{ASM_V3}}}application/{{{ASM_V3}}}windowsSettings/{{http://schemas.microsoft.com/SMI/2005/WindowsSettings}}dpiAware'), 'true')
        supported = root.findall(f'{{{COMPAT_V1}}}compatibility/{{{COMPAT_V1}}}application/{{{COMPAT_V1}}}supportedOS')
        self.assertIn('{old-supported-os}', [node.get('Id') for node in supported])

    def test_reapplying_patch_retains_one_code_page_and_os_entry(self):
        once = utf8_manifest()
        root = ET.fromstring(utf8_manifest(once))
        self.assertEqual(len(root.findall(f'{{{ASM_V3}}}application/{{{ASM_V3}}}windowsSettings/{{{WINDOWS_SETTINGS_2019}}}activeCodePage')), 1)
        supported = root.findall(f'{{{COMPAT_V1}}}compatibility/{{{COMPAT_V1}}}application/{{{COMPAT_V1}}}supportedOS')
        self.assertEqual([node.get('Id') for node in supported].count(WINDOWS_10_GUID), 1)

    def test_unexpected_manifest_fails_instead_of_discarding_settings(self):
        with self.assertRaisesRegex(ValueError, 'manifest root'):
            utf8_manifest(b'<unexpected><setting>keep</setting></unexpected>')


if __name__ == '__main__':
    unittest.main()
