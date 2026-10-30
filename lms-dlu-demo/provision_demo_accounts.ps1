[CmdletBinding()]
param(
    [ValidateSet('all', 'student-a', 'student-b', 'teacher-l')]
    [string]$Alias = 'all',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is unavailable.' }
$root = Join-Path $env:LOCALAPPDATA 'DeepTutor\demo-accounts'
$profiles = @{
    'student-a' = @{ Label = 'Sinh viên A'; File = 'student-a.dpapi' }
    'student-b' = @{ Label = 'Sinh viên B'; File = 'student-b.dpapi' }
    'teacher-l' = @{ Label = 'Giảng viên L'; File = 'teacher-l.dpapi' }
}

New-Item -ItemType Directory -Force -Path $root | Out-Null
$directory = [System.IO.DirectoryInfo]::new($root)
$accessSection = [Security.AccessControl.AccessControlSections]::Access
try {
    # Use the directory APIs so Windows PowerShell writes only the DACL, never SACL or owner.
    if ($directory.PSObject.Methods['GetAccessControl']) {
        $acl = $directory.GetAccessControl($accessSection)
    } else {
        $acl = [System.IO.FileSystemAclExtensions]::GetAccessControl($directory, $accessSection)
    }
    $acl.SetAccessRuleProtection($true, $false)
    $existingRules = $acl.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier])
    foreach ($rule in $existingRules) { $acl.RemoveAccessRuleSpecific($rule) }
    $inheritance = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
    $propagation = [Security.AccessControl.PropagationFlags]::None
    $identities = @(
        [Security.Principal.WindowsIdentity]::GetCurrent().User,
        [Security.Principal.SecurityIdentifier]::new('S-1-5-18'),
        [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
    )
    foreach ($identity in $identities) {
        $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
            $identity, 'FullControl', $inheritance, $propagation, 'Allow')))
    }
    if ($directory.PSObject.Methods['SetAccessControl']) {
        $directory.SetAccessControl($acl)
    } else {
        [System.IO.FileSystemAclExtensions]::SetAccessControl($directory, $acl)
    }
} catch {
    throw "Unable to configure the demo-account DACL before provisioning: $($_.Exception.Message)"
}

$targets = if ($Alias -eq 'all') { @('student-a', 'student-b', 'teacher-l') } else { @($Alias) }
foreach ($key in $targets) {
    $path = Join-Path $root $profiles[$key].File
    if ((Test-Path -LiteralPath $path) -and -not $Force) {
        Write-Warning "$key is already configured; use -Force to replace its DPAPI blob."
        continue
    }
    $secret = Read-Host "Moodle token for $($profiles[$key].Label)" -AsSecureString
    $secret | ConvertFrom-SecureString | Set-Content -LiteralPath $path -NoNewline -Encoding ascii
    Write-Host "$key configured."
}
