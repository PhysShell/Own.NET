using System;
using System.Collections.Generic;
using System.Linq;

// P-016 B0b/B2 (--flow-locals): a real leak distilled from GTM's
// CatalogService.GetProductsFromCatalogWODocuments. A UnitOfWork (IDisposable,
// owning a DbContext) is created as a local and used ONLY through member access
// (uow.ProductCatalogs / uow.TempProducts / uow.GenericRepository<>()) to build a
// DEFERRED IQueryable that is then returned. The bare `uow` never escapes (only
// `uow.Member` does), so the escape filter keeps it tracked; disposed on no path
// -> OWN001. This is the escape-via-projection case the flat D1 detector misses,
// and it is NOT fixable by a naive `using`: that would dispose the context before
// the deferred query runs (ObjectDisposedException). The real fix is to MATERIALIZE
// inside the using (GetProductsFromCatalogWODocumentsFixed below).
namespace Catalog
{
    public class CatalogService
    {
        // OWN001: 'uow' is created, captured into the returned deferred query via
        // member access, and disposed on no path. It is never returned or passed as
        // the bare identifier, so it is not exempted as an escaping local.
        public IQueryable<ProductCatalog> GetProductsFromCatalogWODocuments(DocHeader header)
        {
            Guid sessionId = Guid.NewGuid();
            IQueryable<ProductCatalog> data;
            IUnitOfWork uow = new UnitOfWork(true);
            IQueryable<ProductCatalog> productCatalogs = uow.ProductCatalogs.Where(p => p.DocumentID == null);
            IQueryable<ProductDocuments> productDocuments = uow.GenericRepository<ProductDocuments>().GetAll();

            IQueryable<ProductCatalog> pcwodoc = from pc in productCatalogs
                                                 join pd in productDocuments on pc.ID equals pd.ProductID into a
                                                 from x in a.DefaultIfEmpty()
                                                 where x == null
                                                 select pc;
            if (header == null)
            {
                data = pcwodoc;
            }
            else
            {
                Guid headerid = header.ID;
                data = from p in pcwodoc
                       join tp in uow.TempProducts on new { p.Article, p.ManufacturerID } equals
                           new { tp.Article, tp.ManufacturerID }
                       where p.DocumentID == null && tp.SessionID.Equals(sessionId) && tp.DocumentID.Equals(headerid)
                       select p;
            }
            return data;
        }

        // The correct fix: MATERIALIZE inside the `using` (a naive `using` would
        // dispose before the deferred query executes). `using var` disposes on all
        // paths -> the flow detector skips it -> silent.
        public List<ProductCatalog> GetProductsFromCatalogWODocumentsFixed(DocHeader header)
        {
            using var uowFixed = new UnitOfWork(true);
            IQueryable<ProductCatalog> productCatalogs =
                uowFixed.ProductCatalogs.Where(p => p.DocumentID == null);
            return productCatalogs.ToList();   // materialized before dispose
        }

        // Option B — ownership TRANSFERRED to the caller (the composable fix): the
        // unit of work is `new`'d here but RETURNED, so the caller keeps the context
        // alive across the deferred query's enumeration and disposes it itself:
        //   using var uow = svc.CreateUnitOfWork();
        //   foreach (var p in svc.QueryProducts(uow, header)) { ... }   // ctx alive
        // The bare `uowOwned` escapes via `return`, so the flow detector does not
        // track it -> silent. Unlike the materialize fix, the IQueryable stays
        // composable (the caller can still add .Where()/paging translated to SQL).
        public IUnitOfWork CreateUnitOfWork()
        {
            var uowOwned = new UnitOfWork(true);
            return uowOwned;
        }

        // Option B, the argument form: the unit of work is `new`'d here but handed to
        // a callee that takes ownership (disposal becomes the callee's contract). The
        // bare `uowMoved` escapes via the ARGUMENT, so it is not tracked -> silent.
        public void ImportProducts(DocHeader header)
        {
            var uowMoved = new UnitOfWork(true);
            ConsumeUnitOfWork(uowMoved);
        }

        private static void ConsumeUnitOfWork(IUnitOfWork uow) => uow.Dispose();
    }

    // --- Minimal stand-ins for the GTM domain types: self-contained so the sample
    //     compiles standalone and `new UnitOfWork(...)` binds to an IDisposable. ---

    public interface IUnitOfWork : IDisposable
    {
        IQueryable<ProductCatalog> ProductCatalogs { get; }
        IQueryable<TempProduct> TempProducts { get; }
        IGenericRepository<T> GenericRepository<T>();
    }

    // Owns a DbContext-like resource, so Dispose() is meaningful (NOT dispose-
    // optional) — which is what makes a leaked local matter.
    public sealed class UnitOfWork : IUnitOfWork
    {
        public UnitOfWork(bool isCatalogs) { }
        public IQueryable<ProductCatalog> ProductCatalogs => Enumerable.Empty<ProductCatalog>().AsQueryable();
        public IQueryable<TempProduct> TempProducts => Enumerable.Empty<TempProduct>().AsQueryable();
        public IGenericRepository<T> GenericRepository<T>() => new GenericRepository<T>();
        public void Dispose() { }
    }

    public interface IGenericRepository<T>
    {
        IQueryable<T> GetAll();
    }

    public sealed class GenericRepository<T> : IGenericRepository<T>
    {
        public IQueryable<T> GetAll() => Enumerable.Empty<T>().AsQueryable();
    }

    public class ProductCatalog
    {
        public int ID { get; set; }
        public int? DocumentID { get; set; }
        public string Article { get; set; } = "";
        public int ManufacturerID { get; set; }
    }

    public class ProductDocuments
    {
        public int ID { get; set; }
        public int ProductID { get; set; }
    }

    public class TempProduct
    {
        public string Article { get; set; } = "";
        public int ManufacturerID { get; set; }
        public Guid SessionID { get; set; }
        public Guid DocumentID { get; set; }
    }

    public class DocHeader
    {
        public Guid ID { get; set; }
    }
}
