param(
    [Parameter(Mandatory = $true)]
    [string] $Assembly,

    [Parameter(Mandatory = $true)]
    [string] $Cecil,

    [Parameter(Mandatory = $true)]
    [string] $OutJson,

    [string] $TypePrefix = "",

    [int] $MaxTypes = 0
)

$ErrorActionPreference = "Stop"

$assemblyPath = (Resolve-Path -LiteralPath $Assembly).Path
$cecilPath = (Resolve-Path -LiteralPath $Cecil).Path
Add-Type -Path $cecilPath

function Get-ObfuscatedName($provider) {
    if ($null -eq $provider -or $null -eq $provider.CustomAttributes) {
        return $null
    }
    foreach ($attribute in $provider.CustomAttributes) {
        if ($attribute.AttributeType.Name -ne "ObfuscatedNameAttribute") {
            continue
        }
        if ($attribute.ConstructorArguments.Count -lt 1) {
            continue
        }
        return [string] $attribute.ConstructorArguments[0].Value
    }
    return $null
}

function Get-TypeName($typeRef) {
    if ($null -eq $typeRef) {
        return ""
    }
    return ([string] $typeRef.FullName).Replace("/", "+")
}

function Get-MethodSignature($method) {
    $parameters = @()
    foreach ($parameter in $method.Parameters) {
        $parameters += "$(Get-TypeName $parameter.ParameterType) $($parameter.Name)"
    }
    return "$(Get-TypeName $method.ReturnType) $($method.Name)($($parameters -join ', '))"
}

function Is-CallableMethod($method) {
    if ($method.Name -eq ".cctor" -or $method.Name -eq ".ctor") {
        return $false
    }
    foreach ($prefix in @("get_", "set_", "add_", "remove_")) {
        if ($method.Name.StartsWith($prefix, [System.StringComparison]::Ordinal)) {
            return $false
        }
    }
    return $true
}

function Get-FlattenedTypes($typeDef) {
    $typeDef
    foreach ($nested in $typeDef.NestedTypes) {
        Get-FlattenedTypes $nested
    }
}

$resolver = [Mono.Cecil.DefaultAssemblyResolver]::new()
$resolver.AddSearchDirectory([System.IO.Path]::GetDirectoryName($assemblyPath))
$resolver.AddSearchDirectory([System.IO.Path]::GetDirectoryName($cecilPath))
$readerParameters = [Mono.Cecil.ReaderParameters]::new()
$readerParameters.AssemblyResolver = $resolver
$module = [Mono.Cecil.ModuleDefinition]::ReadModule($assemblyPath, $readerParameters)

$types = New-Object System.Collections.Generic.List[object]
$scanned = 0
foreach ($topLevel in $module.Types) {
    foreach ($type in (Get-FlattenedTypes $topLevel)) {
        if ($type.Name -eq "<Module>") {
            continue
        }
        $obfuscatedType = Get-ObfuscatedName $type
        $runtimeType = (Get-TypeName $type)
        if ($TypePrefix -and -not (
            $runtimeType.StartsWith($TypePrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
            ($obfuscatedType -and $obfuscatedType.StartsWith($TypePrefix, [System.StringComparison]::OrdinalIgnoreCase))
        )) {
            continue
        }
        $scanned += 1
        if ($MaxTypes -gt 0 -and $scanned -gt $MaxTypes) {
            break
        }

        $methods = New-Object System.Collections.Generic.List[object]
        $callableOrdinal = 0
        foreach ($method in $type.Methods) {
            $parameters = @()
            foreach ($parameter in $method.Parameters) {
                $parameters += (Get-TypeName $parameter.ParameterType)
            }
            $currentCallableOrdinal = $null
            if (Is-CallableMethod $method) {
                $currentCallableOrdinal = $callableOrdinal
                $callableOrdinal += 1
            }
            $methods.Add([ordered] @{
                runtime_method = [string] $method.Name
                obfuscated_method = Get-ObfuscatedName $method
                callable_ordinal = $currentCallableOrdinal
                return_type = Get-TypeName $method.ReturnType
                parameter_types = $parameters
                parameter_count = $method.Parameters.Count
                signature = Get-MethodSignature $method
                is_static = [bool] $method.IsStatic
            })
        }

        $types.Add([ordered] @{
            runtime_type = $runtimeType
            obfuscated_type = $obfuscatedType
            method_count = $methods.Count
            methods = $methods
        })
    }
    if ($MaxTypes -gt 0 -and $scanned -gt $MaxTypes) {
        break
    }
}

$document = [ordered] @{
    schema = 1
    assembly = $assemblyPath
    type_prefix = $TypePrefix
    type_count = $types.Count
    types = $types
    evidence_boundary = @(
        "Runtime type and method names are read from the generated Il2CppInterop assembly metadata.",
        "ObfuscatedNameAttribute values are metadata evidence for decomp-name correlation.",
        "This map does not prove method invocation order or Harmony patch safety."
    )
}

$outPath = [System.IO.Path]::GetFullPath($OutJson)
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($outPath)) | Out-Null
$document | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $outPath -Encoding UTF8
Write-Output "Wrote $outPath ($($types.Count) type(s))."
