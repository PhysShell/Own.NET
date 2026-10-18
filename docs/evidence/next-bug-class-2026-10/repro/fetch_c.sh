get() { mkdir -p "c-pairs/$1/$2"; gh api "repos/$3/contents/$4?ref=$5" -H "Accept: application/vnd.github.raw" > "c-pairs/$1/$2/$(basename $4)"; echo "$1/$2 $(wc -l < c-pairs/$1/$2/$(basename $4))"; }
get meziantou base meziantou/Meziantou.Framework src/Meziantou.Framework/DictionaryExtensions.cs 7addb26cfd08a6ed6119a3d0a186486befaa923b
get meziantou fix  meziantou/Meziantou.Framework src/Meziantou.Framework/DictionaryExtensions.cs cf82931e2cea86af40e67eb742f3c1331b65f91e
get maui base dotnet/maui src/Controls/src/Core/BindableObject.cs 7b051d1bbf66d25a3b46c3382ffd25911f16c892
get maui fix  dotnet/maui src/Controls/src/Core/BindableObject.cs 2db8b6af53b620f279d965f323d57f9d002c58da
