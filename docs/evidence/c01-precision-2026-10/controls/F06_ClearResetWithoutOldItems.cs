// Form 6 — DANGEROUS: items are unsubscribed only from e.OldItems; ObservableCollection.Clear() raises Reset
// with OldItems == null, so every item that was in the collection keeps its handler (the H1 post-reveal
// error class, GeometryGroup.cs:91 / PathGeometry). Shared items then retain the owner.
// Oracle: real retention after Clear(). Own.NET: OWN001 on the item subscription. Must stay.
using System;
using System.Collections.ObjectModel;
using System.Collections.Specialized;
using System.ComponentModel;

namespace C01P1.F06
{
    public sealed class Item : INotifyPropertyChanged
    {
        public event PropertyChangedEventHandler? PropertyChanged;
        public void Touch() => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Touch)));
    }

    public sealed class Owner
    {
        private readonly ObservableCollection<Item> _items = new ObservableCollection<Item>();

        public Owner()
        {
            _items.CollectionChanged += OnItemsChanged; // EXPECT before=none after=none
        }

        public ObservableCollection<Item> Items => _items;

        private void OnItemsChanged(object? sender, NotifyCollectionChangedEventArgs e)
        {
            if (e.OldItems != null)
                foreach (Item old in e.OldItems)
                    old.PropertyChanged -= OnItemChanged;
            if (e.NewItems != null)
                foreach (Item item in e.NewItems)
                    item.PropertyChanged += OnItemChanged; // EXPECT before=OWN001 after=OWN001
        }

        private void OnItemChanged(object? sender, PropertyChangedEventArgs e) { }
    }
}
