TEST ATTACHMENTS — WTG DLP Plugin

Use these files when running the manual test cases in docs/test-cases.md.

File                            Used in    Triggers
------------------------------  ---------  ----------------------------------
clean-report.txt                TC-001     Nothing — clean send baseline
                                TC-006
Globex_Industries_Report.txt    TC-008     Rule 2 filename scan
q2-summary.txt                  TC-009     Rule 2 content scan (Globex ref)
Globex_Q2.txt                   TC-016     Rule 2 filename + content scan

Files you must create manually (cannot be stored in git):
  setup.exe       TC-010   Rename any file to .exe to test blocked extension
  script.ps1      TC-010   Alternative: rename to .ps1
  archive.zip     TC-011   ZIP containing a file named malware.exe inside
  data.zip        TC-012   ZIP containing only harmless files (e.g. clean-report.txt)
